/* Draw a diagnostic frame through DRM/KMS and hold it until stdin receives a byte. */
#include <fcntl.h>
#include <linux/input.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/mman.h>
#include <sys/ioctl.h>
#include <unistd.h>
#include <xf86drm.h>
#include <xf86drmMode.h>
#include "display-confirm.h"
#include "display-input.h"

static void draw_frame(void *pixels, const struct drm_mode_create_dumb *buffer, int selected) {
    const uint32_t colors[] = {0x00cc3322, 0x0022aa55, 0x002244cc};
    for (uint32_t y = 0; y < buffer->height; ++y) {
        uint32_t *row = (uint32_t *)((char *)pixels + (size_t)y * buffer->pitch);
        for (uint32_t x = 0; x < buffer->width; ++x) {
            int column = x * 3 / buffer->width;
            row[x] = column == selected ? 0x00f2c94c : colors[column];
        }
    }
}

static int axis_pixel(int value, const struct input_absinfo *axis, int size) {
    if (value <= axis->minimum)
        return 0;
    if (value >= axis->maximum)
        return size - 1;
    return ((int64_t)value - axis->minimum) * (size - 1) /
           ((int64_t)axis->maximum - axis->minimum);
}

static int handle_input(int console, int input, int drm, uint32_t framebuffer, void *pixels,
                        const struct drm_mode_create_dumb *buffer,
                        struct touch_input *touch, int confirm) {
    struct pollfd sources[] = {{console, POLLIN, 0}, {input, POLLIN, 0}};
    int button_event = 0;
    int pressed_button = -1;
    while (poll(sources, 2, -1) > 0) {
        if (sources[0].revents) {
            char byte;
            (void)read(console, &byte, 1);
            return confirm ? 42 : 0;
        }
        struct input_event event;
        if (!(sources[1].revents & POLLIN) || read(input, &event, sizeof(event)) != sizeof(event))
            return 1;
        if (event.type == EV_SYN && event.code == SYN_DROPPED)
            return confirm ? 42 : 1;
        if (touch->slots && event.type == EV_ABS) {
            int action = touch_event(touch, &event);
            if (action)
                button_event = action;
        } else if (!touch->slots) {
            if (event.type == EV_ABS && event.code == ABS_X)
                touch->x.value = event.value;
            else if (event.type == EV_ABS && event.code == ABS_Y)
                touch->y.value = event.value;
            else if (event.type == EV_KEY && (event.code == BTN_LEFT || event.code == BTN_TOUCH) && event.value != 2)
                button_event = event.value ? 1 : 2;
        }
        if (event.type == EV_SYN && event.code == SYN_REPORT) {
            if (touch->blocked) {
                if (!touch->count)
                    touch->blocked = 0;
                button_event = 0;
                pressed_button = -1;
                continue;
            }
            if (!button_event)
                continue;
            int x = touch->slots ? touch->contacts[touch->selected].x : touch->x.value;
            int y = touch->slots ? touch->contacts[touch->selected].y : touch->y.value;
            int px = axis_pixel(x, &touch->x, buffer->width);
            int py = axis_pixel(y, &touch->y, buffer->height);
            if (confirm) {
                int hit = -1;
                for (int save = 0; save <= 1; ++save) {
                    struct rect button = confirm_button(buffer->width, buffer->height, save);
                    if (px >= button.x && px < button.x + button.width &&
                        py >= button.y && py < button.y + button.height)
                        hit = save;
                }
                if (button_event == 1)
                    pressed_button = hit;
                else if (hit >= 0 && hit == pressed_button)
                    return hit ? 0 : 42;
                else
                    pressed_button = -1;
                button_event = 0;
                continue;
            }
            if (button_event == 1) {
                button_event = 0;
                continue;
            }
            draw_frame(pixels, buffer, px * 3 / buffer->width);
            if (drmModeDirtyFB(drm, framebuffer, NULL, 0))
                return 1;
            printf("AIOS_POINTER_TAP %d %d\n", px, py);
            fflush(stdout);
            button_event = 0;
        }
    }
    return 1;
}

int main(void) {
    int result = 1;
    int fd = open("/dev/dri/card0", O_RDWR | O_CLOEXEC);
    if (fd < 0) {
        perror("open DRM card");
        return result;
    }
    drmModeRes *resources = drmModeGetResources(fd);
    drmModeConnector *connector = NULL;
    drmModeCrtc *previous = NULL;
    struct drm_mode_create_dumb buffer = {0};
    void *pixels = MAP_FAILED;
    uint32_t framebuffer = 0;
    int console = -1;
    if (!resources || resources->count_crtcs < 1)
        goto cleanup;
    for (int index = 0; index < resources->count_connectors; ++index) {
        connector = drmModeGetConnector(fd, resources->connectors[index]);
        if (connector && connector->connection == DRM_MODE_CONNECTED && connector->count_modes)
            break;
        drmModeFreeConnector(connector);
        connector = NULL;
    }
    if (!connector)
        goto cleanup;
    drmModeEncoder *encoder = drmModeGetEncoder(fd, connector->encoder_id);
    uint32_t crtc = encoder && encoder->crtc_id ? encoder->crtc_id : resources->crtcs[0];
    drmModeFreeEncoder(encoder);
    previous = drmModeGetCrtc(fd, crtc);
    drmModeModeInfo mode = connector->modes[0];
    buffer.width = mode.hdisplay;
    buffer.height = mode.vdisplay;
    buffer.bpp = 32;
    if (drmIoctl(fd, DRM_IOCTL_MODE_CREATE_DUMB, &buffer) < 0)
        goto cleanup;
    struct drm_mode_map_dumb map = {.handle = buffer.handle};
    if (drmIoctl(fd, DRM_IOCTL_MODE_MAP_DUMB, &map) < 0)
        goto cleanup;
    pixels = mmap(NULL, buffer.size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, map.offset);
    if (pixels == MAP_FAILED)
        goto cleanup;
    console = open("/dev/console", O_RDONLY | O_CLOEXEC);
    if (console < 0)
        goto cleanup;
    if (drmModeAddFB(fd, buffer.width, buffer.height, 24, 32, buffer.pitch, buffer.handle, &framebuffer))
        goto cleanup;
    fprintf(stderr, "AIOS display allocated %ux%u buffer\n", buffer.width, buffer.height);
    char request[514];
    while (fgets(request, sizeof(request), stdin)) {
        char *newline = strchr(request, '\n');
        if (!newline)
            break;
        *newline = '\0';
        int confirm = request[0] != '\0';
        struct touch_input touch;
        int input = -1;
        int outcome = 1;
        if (!confirm)
            draw_frame(pixels, &buffer, -1);
        if (!confirm || !draw_confirmation(pixels, &buffer, request))
            input = open_input(&touch);
        if (input >= 0 &&
            !drmModeSetCrtc(fd, crtc, framebuffer, 0, 0, &connector->connector_id, 1, &mode)) {
            printf("%s %ux%u\n", confirm ? "AIOS_CONFIRM_READY" : "AIOS_FRAME_READY",
                   buffer.width, buffer.height);
            fflush(stdout);
            outcome = handle_input(console, input, fd, framebuffer, pixels, &buffer, &touch, confirm);
            if (previous && previous->mode_valid)
                drmModeSetCrtc(fd, crtc, previous->buffer_id, previous->x, previous->y,
                               &connector->connector_id, 1, &previous->mode);
            else
                drmModeSetCrtc(fd, crtc, 0, 0, 0, NULL, 0, NULL);
        }
        if (input >= 0)
            close(input);
        printf("RESULT %d\n", outcome);
        fflush(stdout);
    }
    result = 0;

cleanup:
    if (result && result != 42)
        fprintf(stderr, "DRM diagnostic failed to display a frame\n");
    if (framebuffer)
        drmModeRmFB(fd, framebuffer);
    if (pixels != MAP_FAILED)
        munmap(pixels, buffer.size);
    if (buffer.handle) {
        struct drm_mode_destroy_dumb destroy = {.handle = buffer.handle};
        drmIoctl(fd, DRM_IOCTL_MODE_DESTROY_DUMB, &destroy);
    }
    drmModeFreeCrtc(previous);
    drmModeFreeConnector(connector);
    drmModeFreeResources(resources);
    if (console >= 0)
        close(console);
    close(fd);
    return result;
}
