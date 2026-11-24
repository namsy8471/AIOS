/* Single-contact taps from the Linux type B slot protocol. */
#include <glob.h>
#include <string.h>

#define TOUCH_SLOTS 64

struct touch_input {
    struct input_absinfo x, y;
    int slots, slot, selected, count, blocked;
    struct {
        int active, x, y;
    } contacts[TOUCH_SLOTS];
};

static int open_input(struct touch_input *state, enum panel_priority panel) {
    glob_t nodes = {0};
    if (glob("/dev/input/event*", 0, NULL, &nodes))
        return -1;
    int chosen = -1, chosen_rank = 0;
    for (size_t i = 0; i < nodes.gl_pathc; ++i) {
        struct touch_input candidate = {.selected = -1};
        struct input_absinfo slot;
        int fd = open(nodes.gl_pathv[i], O_RDONLY | O_CLOEXEC);
        if (fd < 0)
            continue;
        unsigned char axes[(ABS_MAX + 8) / 8] = {0};
        if (ioctl(fd, EVIOCGBIT(EV_ABS, sizeof(axes)), axes) < 0) {
            close(fd);
            continue;
        }
        if (axes[ABS_MT_SLOT / 8] & (1u << (ABS_MT_SLOT % 8))) {
            if (ioctl(fd, EVIOCGABS(ABS_MT_SLOT), &slot) < 0 ||
                slot.minimum != 0 || slot.maximum < 0 || slot.maximum >= TOUCH_SLOTS ||
                slot.value < 0 || slot.value > slot.maximum ||
                ioctl(fd, EVIOCGABS(ABS_MT_POSITION_X), &candidate.x) < 0 ||
                ioctl(fd, EVIOCGABS(ABS_MT_POSITION_Y), &candidate.y) < 0) {
                close(fd);
                continue;
            }
            candidate.slots = slot.maximum + 1;
            candidate.slot = slot.value;
            int tracking[TOUCH_SLOTS + 1] = {ABS_MT_TRACKING_ID};
            int x[TOUCH_SLOTS + 1] = {ABS_MT_POSITION_X};
            int y[TOUCH_SLOTS + 1] = {ABS_MT_POSITION_Y};
            size_t bytes = (candidate.slots + 1) * sizeof(int);
            if (ioctl(fd, EVIOCGMTSLOTS(bytes), tracking) < 0 ||
                ioctl(fd, EVIOCGMTSLOTS(bytes), x) < 0 || ioctl(fd, EVIOCGMTSLOTS(bytes), y) < 0) {
                close(fd);
                continue;
            }
            for (int j = 0; j < candidate.slots; ++j) {
                candidate.contacts[j].active = tracking[j + 1] >= 0;
                candidate.contacts[j].x = x[j + 1];
                candidate.contacts[j].y = y[j + 1];
                candidate.count += candidate.contacts[j].active;
            }
            candidate.blocked = candidate.count != 0;
        } else if (ioctl(fd, EVIOCGABS(ABS_X), &candidate.x) < 0 ||
                   ioctl(fd, EVIOCGABS(ABS_Y), &candidate.y) < 0) {
            close(fd);
            continue;
        }
        char name[128] = {0};
        if (ioctl(fd, EVIOCGNAME(sizeof(name) - 1), name) < 0) {
            close(fd);
            continue;
        }
        int rank = touch_rank(name, candidate.slots != 0, panel);
        if (rank <= chosen_rank || candidate.x.maximum <= candidate.x.minimum ||
            candidate.y.maximum <= candidate.y.minimum) {
            close(fd);
            continue;
        }
        if (chosen >= 0)
            close(chosen);
        chosen = fd;
        chosen_rank = rank;
        *state = candidate;
    }
    globfree(&nodes);
    return chosen;
}

static int touch_event(struct touch_input *state, const struct input_event *event) {
    if (event->type == EV_ABS && event->code == ABS_MT_SLOT) {
        state->slot = event->value;
        return 0;
    }
    if (event->type != EV_ABS || state->slot < 0 || state->slot >= state->slots)
        return 0;
    int slot = state->slot;
    if (event->code == ABS_MT_POSITION_X) {
        state->contacts[slot].x = event->value;
    } else if (event->code == ABS_MT_POSITION_Y) {
        state->contacts[slot].y = event->value;
    } else if (event->code == ABS_MT_TRACKING_ID && event->value >= 0) {
        if (state->contacts[slot].active || state->count)
            state->blocked = 1;
        if (!state->contacts[slot].active)
            ++state->count;
        state->contacts[slot].active = 1;
        if (!state->blocked) {
            state->selected = slot;
            return 1;
        }
    } else if (event->code == ABS_MT_TRACKING_ID && state->contacts[slot].active) {
        state->contacts[slot].active = 0;
        --state->count;
        if (slot == state->selected && !state->blocked)
            return 2;
    }
    return 0;
}
