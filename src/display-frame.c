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

static int handle_input(int input, int drm, uint32_t framebuffer, void *pixels,
                        const struct drm_mode_create_dumb *buffer,
                        struct input_absinfo *x, struct input_absinfo *y) {
    struct pollfd sources[] = {{STDIN_FILENO, POLLIN, 0}, {input, POLLIN, 0}};
    int tap_pending = 0;
    while (poll(sources, 2, -1) > 0) {
        if (sources[0].revents) {
            (void)getchar();
            return 0;
        }
        struct input_event event;
        if (!(sources[1].revents & POLLIN) || read(input, &event, sizeof(event)) != sizeof(event))
            return 1;
        if (event.type == EV_ABS && event.code == ABS_X)
            x->value = event.value;
        else if (event.type == EV_ABS && event.code == ABS_Y)
            y->value = event.value;
        else if (event.type == EV_KEY && (event.code == BTN_LEFT || event.code == BTN_TOUCH) && event.value == 0)
            tap_pending = 1;
        else if (event.type == EV_SYN && event.code == SYN_REPORT && tap_pending) {
            int px = axis_pixel(x->value, x, buffer->width);
            int py = axis_pixel(y->value, y, buffer->height);
            draw_frame(pixels, buffer, px * 3 / buffer->width);
            if (drmModeDirtyFB(drm, framebuffer, NULL, 0))
                return 1;
            printf("AIOS_POINTER_TAP %d %d\n", px, py);
            fflush(stdout);
            tap_pending = 0;
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
    int input = -1;
    struct input_absinfo x, y;
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
    draw_frame(pixels, &buffer, -1);
    input = open("/dev/input/event0", O_RDONLY | O_CLOEXEC);
    if (input < 0 || ioctl(input, EVIOCGABS(ABS_X), &x) < 0 ||
        ioctl(input, EVIOCGABS(ABS_Y), &y) < 0 ||
        x.maximum <= x.minimum || y.maximum <= y.minimum)
        goto cleanup;
    if (drmModeAddFB(fd, buffer.width, buffer.height, 24, 32, buffer.pitch, buffer.handle, &framebuffer))
        goto cleanup;
    if (drmModeSetCrtc(fd, crtc, framebuffer, 0, 0, &connector->connector_id, 1, &mode))
        goto cleanup;
    printf("AIOS_FRAME_READY %ux%u\n", buffer.width, buffer.height);
    fflush(stdout);
    result = handle_input(input, fd, framebuffer, pixels, &buffer, &x, &y);
    if (previous && previous->mode_valid)
        drmModeSetCrtc(fd, crtc, previous->buffer_id, previous->x, previous->y,
                       &connector->connector_id, 1, &previous->mode);

cleanup:
    if (result)
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
    if (input >= 0)
        close(input);
    close(fd);
    return result;
}
