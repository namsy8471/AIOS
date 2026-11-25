#include <assert.h>
#include "../src/display-route.h"

int main(void) {
    enum panel_priority inner = panel_rank(DRM_MODE_CONNECTOR_DSI, 1080, 2640);
    enum panel_priority other_dsi = panel_rank(DRM_MODE_CONNECTOR_DSI, 1920, 1080);
    enum panel_priority virtual = panel_rank(DRM_MODE_CONNECTOR_VIRTUAL, 1080, 2640);
    assert(inner > other_dsi && other_dsi > virtual);
    assert(touch_rank("sec_touchscreen", 1, inner) == 3);
    assert(touch_rank("QEMU Virtio MultiTouch", 1, inner) == 0);
    assert(touch_rank("sec_touchscreen", 1, other_dsi) == 0);
    assert(touch_rank("sec_touchscreen", 1, virtual) == 0);
    assert(touch_rank("sec_touchscreen", 0, inner) == 0);
    assert(touch_rank("sec_touchscreen2", 1, inner) == 0);
    assert(touch_rank("sec_touchpad", 1, inner) == 0);
    assert(touch_rank("QEMU Virtio MultiTouch", 1, virtual) > touch_rank("QEMU Virtio Tablet", 0, virtual));
    return 0;
}
