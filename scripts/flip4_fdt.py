"""Read flattened device trees from the Flip4 reference payloads."""
import struct


def trees(image):
    magic = bytes.fromhex("d00dfeed")
    offset = image.find(magic)
    while offset != -1:
        _, size, _, _, _, version, *_ = struct.unpack_from(">10I", image, offset)
        if version < 17 or size < 40 or size > len(image) - offset:
            raise ValueError(f"invalid FDT header at byte {offset}")
        yield image[offset:offset + size]
        offset = image.find(magic, offset + size)


def nodes(tree):
    _, _, struct_offset, strings_offset, _, _, _, _, strings_size, struct_size = struct.unpack_from(">10I", tree)
    data = tree[struct_offset:struct_offset + struct_size]
    strings = tree[strings_offset:strings_offset + strings_size]
    parents = []
    offset = 0
    while offset < len(data):
        token, = struct.unpack_from(">I", data, offset)
        offset += 4
        if token == 1:
            end = data.index(0, offset)
            parents.append((data[offset:end].decode(), {}))
            offset = (end + 4) & ~3
        elif token == 2:
            yield "/".join(name for name, _ in parents), parents.pop()[1]
        elif token == 3:
            size, name_offset = struct.unpack_from(">II", data, offset)
            name = strings[name_offset:strings.index(0, name_offset)].decode()
            offset += 8
            parents[-1][1][name] = data[offset:offset + size]
            offset = (offset + size + 3) & ~3
        elif token == 9:
            return
        elif token != 4:
            raise ValueError(f"unexpected FDT token {token}")
