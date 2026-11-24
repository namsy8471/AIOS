/* Draw a diagnostic frame through DRM/KMS and hold it until stdin receives a byte. */
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/mman.h>
#include <unistd.h>
#include <xf86drm.h>
#include <xf86drmMode.h>

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
    const uint32_t colors[] = {0x00cc3322, 0x0022aa55, 0x002244cc};
    for (uint32_t y = 0; y < buffer.height; ++y) {
        uint32_t *row = (uint32_t *)((char *)pixels + (size_t)y * buffer.pitch);
        for (uint32_t x = 0; x < buffer.width; ++x)
            row[x] = colors[x * 3 / buffer.width];
    }
    if (drmModeAddFB(fd, buffer.width, buffer.height, 24, 32, buffer.pitch, buffer.handle, &framebuffer))
        goto cleanup;
    if (drmModeSetCrtc(fd, crtc, framebuffer, 0, 0, &connector->connector_id, 1, &mode))
        goto cleanup;
    printf("AIOS_FRAME_READY %ux%u\n", buffer.width, buffer.height);
    fflush(stdout);
    (void)getchar();
    if (previous && previous->mode_valid)
        drmModeSetCrtc(fd, crtc, previous->buffer_id, previous->x, previous->y,
                       &connector->connector_id, 1, &previous->mode);
    result = 0;

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
    close(fd);
    return result;
}
