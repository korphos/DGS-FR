"""
Utilitaires pour lire et reconstruire les archives .arc de TGAAC.

Structure ARC :
  Header (8 bytes) : magic(4) + version(2) + nb_entries(2)
  Index  : nb_entries × 144 bytes
    [0:128]   filename (null-padded, chemin Windows)
    [128:132] ext_hash (0x242bb29a pour .gmd)
    [132:136] compressed_size
    [136:140] decompressed_size | flags
    [140:144] absolute_offset dans le fichier
  Data section : commence alignée à 0x8000, chaque entrée = zlib.compress(gmd_data)
"""

import struct
import zlib


DATA_SECTION_ALIGN = 0x8000  # les données commencent toujours à 0x8000


def read_arc(data: bytes) -> list[tuple[str, bytes]]:
    """
    Parse un fichier ARC et retourne [(filename, raw_gmd_bytes), ...].
    """
    count = struct.unpack_from('<H', data, 6)[0]
    entries = []
    for i in range(count):
        base = 8 + i * 144
        name = data[base:base+128].rstrip(b'\x00').decode('utf-8', errors='replace')
        comp_size = struct.unpack_from('<I', data, base+132)[0]
        offset = struct.unpack_from('<I', data, base+140)[0]
        raw = zlib.decompress(data[offset:offset+comp_size])
        entries.append((name, raw))
    return entries


def write_arc(entries: list[tuple[str, bytes]], original_header: bytes,
              data_start: int | None = None) -> bytes:
    """
    Reconstruit un fichier ARC à partir de la liste [(filename, raw_gmd_bytes)].
    Conserve le magic, la version et le nombre d'entrées de l'en-tête original.
    data_start : offset où commence la section data (auto-calculé si None).
    """
    count = len(entries)
    magic = original_header[0:4]
    version = original_header[4:6]

    # Construit l'index (144 bytes par entrée)
    index_size = 8 + count * 144
    if data_start is None:
        data_start = DATA_SECTION_ALIGN
        # Agrandir si nécessaire (aligner sur la prochaine puissance de 2)
        while data_start < index_size:
            data_start *= 2
    assert index_size <= data_start, f"Index trop grand ({index_size} > {data_start})"

    # Compresse toutes les données d'abord pour calculer les offsets
    compressed_blobs = []
    for name, raw in entries:
        blob = zlib.compress(raw, level=6)
        compressed_blobs.append(blob)

    # Calcule les offsets absolus dans la section data
    offsets = []
    cur = data_start
    for blob in compressed_blobs:
        offsets.append(cur)
        cur += len(blob)

    # Construit le header ARC
    header = magic + version + struct.pack('<H', count)
    # Padding entre header (8 bytes) et index entries pour atteindre 8 bytes
    # (les entries commencent directement à offset 8)

    # Construit l'index
    index_entries = bytearray()
    for i, ((name, raw), blob, off) in enumerate(zip(entries, compressed_blobs, offsets)):
        entry = bytearray(144)
        name_bytes = name.encode('utf-8')
        entry[0:len(name_bytes)] = name_bytes
        struct.pack_into('<I', entry, 128, 0x242bb29a)  # ext_hash pour .gmd
        struct.pack_into('<I', entry, 132, len(blob))    # compressed_size
        struct.pack_into('<I', entry, 136, len(raw) | 0x40000000)  # decomp_size + flag
        struct.pack_into('<I', entry, 140, off)           # absolute_offset
        index_entries += entry

    # Assemble : header + index + padding + data
    index_section = bytes(header) + bytes(index_entries)
    padding = bytes(data_start - len(index_section))
    data_section = b''.join(compressed_blobs)

    return index_section + padding + data_section
