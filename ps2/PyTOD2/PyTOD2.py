# pip install pyinstaller
# Windows Freeze: Run > cmd > pyinstaller --onefile --noconsole --icon favicon.ico PyTOD2.py

from tkinter import *
from tkinter import filedialog
import tkinter.messagebox as box

import sys
import os
import re
import json
import struct
import subprocess
import shutil
import string

#Prevents PC becoming hostage
from subprocess import CREATE_NO_WINDOW

#Copy SLPS file and rename to new_SLPS
from shutil import copyfile

#For Hyperlinks in the GUI
import webbrowser

def callback(url):
    webbrowser.open_new(url)

low_bits = 0x3F
high_bits = 0xFFFFFFC0
pointer_begin = 0xDD320
pointer_end = 0xE62EF
movie_begin = 0xE62F0
movie_end = 0xE631F

tags = {0x4: 'color', 0x5: 'size', 0x6: 'num', 0x7: 'char', 0x8: 'item', 0x9: 'button'}
names = {1: 'Kyle', 2: 'Reala', 3: 'Loni', 4: 'Judas', 5: 'Nanaly', 6: 'Harold' }

com_tag = r'(<\w+:?\w+>)'
hex_tag = r'(\{[0-9A-F]{2}\})'

printable = ''.join((string.digits,string.ascii_letters,string.punctuation,' '))

def get_pointers():
    f = open('SLPS_251.72', 'rb')
    f.seek(pointer_begin, 0)
    pointers = []

    while f.tell() < pointer_end:
        p = struct.unpack('<L', f.read(4))[0]
        pointers.append(p)

    f.close()
    return pointers

def get_movie_pointers():
    f = open("SLPS_251.72", 'rb')
    f.seek(movie_begin, 0)
    movie_pointers = []

    while f.tell() < movie_end:
        p = struct.unpack('<L', f.read(4))[0]
        movie_pointers.append(p)

    f.close()
    return movie_pointers

def extract_movie():
    f = open('MOVIE.FPB', 'rb')
    mkdir('MOVIE')
    movie_pointers = get_movie_pointers()
    
    for i in range(len(movie_pointers) - 1):
        remainder = movie_pointers[i] & low_bits
        start = movie_pointers[i] & high_bits
        end = (movie_pointers[i+1] & high_bits) - remainder
        f.seek(start, 0)
        size = (end - start)
        if size == 0:
            continue
        data = f.read(size)
        extension = 'mpeg'
        o = open('MOVIE/' + '%05d.%s' % (i, extension), 'wb')
        o.write(data)
        o.close()

    f.close()

def mkdir(name):
    try: os.mkdir(name)
    except: pass

def compress_comptoe(name, ctype=1):
    c = '-c%d' % ctype
    subprocess.run(['comptoe.exe', c, name, name + '.c'], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)

def decompress_comptoe(name):
    subprocess.run(['comptoe.exe', '-d', name, name + '.d'], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)

def validate_comptoe_roundtrip(
    source_file,
    compressed_file
):
    roundtrip_file = compressed_file + '.d'

    if os.path.exists(roundtrip_file):
        os.remove(roundtrip_file)

    decompress_comptoe(compressed_file)

    if not os.path.isfile(roundtrip_file):
        raise RuntimeError(
            f'Decompression validation failed: '
            f'{roundtrip_file} was not created'
        )

    with open(source_file, 'rb') as source:
        source_data = source.read()

    with open(roundtrip_file, 'rb') as result:
        roundtrip_data = result.read()

    os.remove(roundtrip_file)

    if roundtrip_data != source_data:
        raise RuntimeError(
            f'Compression round-trip mismatch: '
            f'{source_file}'
        )

# by flame1234
def decode(param):
    a2 = param
    a3 = 0x993F
    a1 = 0x9940
    if  a3 >= a2:
        a2 = a1
    a1 = a2 >> 8
    a0 = a2 & 0xFF
    t0 = True if a1 < 0xE0 else False
    v1 = a1 - 0x40
    a3 = a0 - 1
    a2 = True if a0 < 0x80 else False
    if t0 == False:
        a1 = v1 & 0xFFFF
    t1 = a1 - 0x99
    t0 = t1 & 0xFFFF
    v0 = 0xBB
    a1 = t0 * v0
    if a2 == False:
        a0 = a3 & 0xFFFF
    t2 = True if a0 < 0x5D else False
    v1 = a0 - 1
    if t2 == False:
        a0 = v1 & 0xFFFF
    t5 = a0 - 0x40
    t4 = t5 & 0xFFFF
    t3 = a1 + t4
    v0 = t3 & 0xFFFF

    return v0

def extract_fpb():
    f = open('FILE.FPB', 'rb')
    json_file = open('FPB.json', 'r')
    json_data = json.load(json_file)
    #ext_file = open('TREE.json', 'r')
    #ext_data = json.load(ext_file)
    #ext_file.close()
    pointers = get_pointers()
    mkdir('FPB')
    
    for i in range(len(pointers) - 1):
        remainder = pointers[i] & low_bits
        start = pointers[i] & high_bits
        end = (pointers[i+1] & high_bits) - remainder
        size = end - start
        if size == 0:
            #json_data[i] = 'dummy'
            continue
        f.seek(start, 0)
        data = f.read(size)
        extension = json_data['%05d' %i]
        #if ('%05d' % i) in ext_data.keys():
        #    extension = ext_data['%05d' % i]
        #json_data['%05d' % i] = extension
        o = open('FPB/' + '%05d.%s' % (i, extension), 'wb')
        o.write(data)
        o.close()

    #json.dump(json_data, json_file, indent = 4)
    f.close()

def move_sced():
    mkdir('SCED')
    sced_dir = os.getcwd() + '/SCED/'
    
    for folder in os.listdir('SCPK'):
        if not os.path.isdir('SCPK/' + folder):
            continue
        f = sorted(os.listdir('SCPK/' + folder))[-1]
        new_name = '%s_%s.sced' % (folder, f.split('.')[0])
        shutil.copy(os.path.join('SCPK', folder, f), sced_dir + new_name)

def extract_scpk():
    mkdir('SCPK')
    mkdir('SCPK_HEADERS')

    json_data = {}

    for file in sorted(os.listdir('FPB')):
        if not file.lower().endswith('.scpk'):
            continue

        input_path = os.path.join('FPB', file)
        index = os.path.splitext(file)[0]

        with open(input_path, 'rb') as f:
            header = f.read(16)

            if len(header) != 16:
                raise RuntimeError(
                    f'{file}: truncated SCPK header'
                )

            if header[:4] != b'SCPK':
                continue

            member_count = struct.unpack_from(
                '<L',
                header,
                8
            )[0]

            mkdir(os.path.join('SCPK', index))

            header_path = os.path.join(
                'SCPK_HEADERS',
                index + '.bin'
            )

            with open(header_path, 'wb') as header_file:
                header_file.write(header)

            sizes = []

            for member_index in range(member_count):
                size_data = f.read(4)

                if len(size_data) != 4:
                    raise RuntimeError(
                        f'{file}: truncated size table at '
                        f'member {member_index}'
                    )

                sizes.append(
                    struct.unpack('<L', size_data)[0]
                )

            json_data[index] = {}

            for member_index, member_size in enumerate(sizes):
                extension = (
                    'sced'
                    if member_index == member_count - 1
                    else 'bin'
                )

                output_path = os.path.join(
                    'SCPK',
                    index,
                    f'{member_index:02d}.{extension}'
                )

                member_data = f.read(member_size)

                if len(member_data) != member_size:
                    raise RuntimeError(
                        f'{file}: member {member_index} is truncated. '
                        f'Expected {member_size} bytes, '
                        f'got {len(member_data)}.'
                    )

                if not member_data:
                    raise RuntimeError(
                        f'{file}: member {member_index} is empty'
                    )

                compression_type = member_data[0]
                json_data[index][str(member_index)] = compression_type

                with open(output_path, 'wb') as output:
                    output.write(member_data)

                if (
                    member_index == member_count - 1
                    and compression_type in (1, 3)
                ):
                    decompressed_path = output_path + '.d'

                    if os.path.exists(decompressed_path):
                        os.remove(decompressed_path)

                    decompress_comptoe(output_path)

                    if not os.path.isfile(decompressed_path):
                        raise RuntimeError(
                            f'{file}: decompression failed for '
                            f'{output_path}'
                        )

                    os.remove(output_path)
                    os.replace(decompressed_path, output_path)

    with open('SCPK.json', 'w', encoding='utf-8') as json_file:
        json.dump(json_data, json_file, indent=4)


def extract_sced():
    move_sced()
    extract_sced_skit()

def extract_sced_skit():
    mkdir('TXT')
    mkdir('TXT_EN')
    json_file = open('TBL.json', 'r')
    #json_file2 = open('TBL2.json', 'w')
    json_data = json.load(json_file)
    json_file.close()
    sced_file = open('SCED.json', 'w')
    sced_data = {}
    #sced_file = open('sced.json', 'r')
    #sced_data = json.load(sced_file)
    #sced_file.close()
    
    #char_file = open('00019.bin', 'r', encoding='cp932')
    #char_index = char_file.read()
    #char_file.close()

    for name in os.listdir('SCED/'):
        f = open('SCED/' + name, 'rb')
        header = f.read(4)
        if header != b'\x53\x43\x45\x44':
            continue
        o = open('TXT/' + name + '.txt', 'w', encoding = 'utf-8')
        sced_data[name] = []
        pointer_block = struct.unpack('<L', f.read(4))[0]
        text_block = struct.unpack('<L', f.read(4))[0]
        fsize = os.path.getsize('SCED/' + name)
        text_pointers = []
        addrs = []
        f.seek(pointer_block, 0)
        
        while f.tell() < text_block:
            b = f.read(1)
            if b == b'\xF8':
                addr = struct.unpack('<H', f.read(2))[0]
                #if f.tell() - 2 in sced_data[name]:
                if (addr < fsize - text_block) and (addr > 0):
                    addrs.append(f.tell() - 2)
                    text_pointers.append(addr)

        for i in range(len(text_pointers)):
            f.seek(text_block + text_pointers[i] - 1, 0)
            b = f.read(1)
            if b != b'\x00':
                continue
            sced_data[name].append(addrs[i])
            b = f.read(1)
            while b != b'\x00':
                b = ord(b)
                if (b >= 0x99 and b <= 0x9F) or (b >= 0xE0 and b <= 0xE4):
                    c = (b << 8) + ord(f.read(1))
                    #if str(c) not in json_data.keys():
                    #    json_data[str(c)] = char_index[decode(c)]
                    o.write(json_data[str(c)])
                elif b == 0x1:
                    o.write('\n')
                elif b in (0x3, 0x4, 0x5, 0x6, 0x7, 0x8, 0x9, 0xB):
                    b2 = struct.unpack('<L', f.read(4))[0]
                    if b in tags:
                        if b == 0x7 and b2 in names:
                            o.write('<%s>' % names[b2])
                        else:
                            o.write('<%s:%08X>' % (tags[b], b2))
                    else:
                        o.write('<%02X:%08X>' % (b, b2))
                elif chr(b) in printable:
                    o.write(chr(b))
                elif b >= 0xA1 and b < 0xE0:
                    o.write(struct.pack('B', b).decode('cp932'))
                elif b in (0x12, 0x14, 0x15, 0x16, 0x17, 0x18):
                    o.write('{%02X}' % b)
                    next_b = b''
                    while next_b not in (b'\xBC', b'\xC0'):
                        next_b = f.read(1)
                        o.write('{%02X}' % ord(next_b))
                else:
                    o.write('{%02X}' % b)
                b = f.read(1)
            o.write('\n-----------------------\n')
        f.close()
        o.close()
        
    #json.dump(json_data, json_file2, indent=4)
    json.dump(sced_data, sced_file, indent=4)

def insert_sced():
    json_file = open('TBL.json', 'r')
    sced_json = open('SCED.json', 'r')
    table = json.load(json_file)
    sced_data = json.load(sced_json)
    json_file.close()
    sced_json.close()
    
    itable = dict([[i,struct.pack('>H', int(j))] for j,i in table.items()])
    itags = dict([[i,j] for j,i in tags.items()])
    inames = dict([[i,j] for j,i in names.items()])
    
    mkdir('SCED_NEW/')

    for name in os.listdir('txt_en'):
        f = open('txt_en/' + name, 'r', encoding='utf8')
        name = name[:-4]
        sced = open('sced/' + name, 'rb')
        o = open('sced_new/' + name, 'wb')

        txts = []
        sizes = []
        txt = bytearray()

        for line in f:
            line = line.strip('\x0A')
            if len(line) > 0:
                if line[0] == '#':
                    continue
            if '-----------------------' in line:
                txts.append(txt[:-1] + b'\x00')
                sizes.append(len(txt))
                txt = bytearray()
            else:
                string_hex = re.split(hex_tag, line)
                string_hex = [sh for sh in string_hex if sh]
                for s in string_hex:
                    if re.match(hex_tag, s):
                        txt += (struct.pack('B', int(s[1:3], 16)))
                    else:
                        s_com = re.split(com_tag, s)
                        s_com = [sc for sc in s_com if sc]
                        for c in s_com:
                            if re.match(com_tag, c):
                                if ':' in c:
                                    split = c.split(':') 
                                    if split[0][1:] in itags.keys():
                                        txt += (struct.pack('B', itags[split[0][1:]]))
                                    else:
                                        txt += (struct.pack('B', int(split[0][1:], 16)))
                                    txt += (struct.pack('<I', int(split[1][:8], 16)))
                                else:
                                    txt += struct.pack('B', 0x7)
                                    txt += struct.pack('<I', inames[c[1:-1]])
                                    
                            else:
                                for c2 in c:
                                    if c2 in itable.keys():
                                        txt += itable[c2]
                                    else:
                                        txt += c2.encode('cp932')
                txt += (b'\x01')
                
        f.close()
        
        sced.seek(8, 0)
        pointer_block = struct.unpack('<L', sced.read(4))[0]
        sced.seek(0, 0)
        header = sced.read(pointer_block)
        o.write(header + b'\x00')
        sced.close()

        pos = 1
        for i in range(len(txts)):
            o.seek(sced_data[name][i], 0)
            o.write(struct.pack('<H', pos))
            pos += sizes[i]

        o.seek(pointer_block + 1, 0)
        
        for t in txts:
            o.write(t)
            
        o.close()

def pack_scpk():
    mkdir('SCPK_PACKED')

    with open('SCPK.json', 'r', encoding='utf-8') as json_file:
        json_data = json.load(json_file)

    translated_files = sorted(
        filename
        for filename in os.listdir('SCED_NEW')
        if filename.lower().endswith('.sced')
        and os.path.isfile(
            os.path.join('SCED_NEW', filename)
        )
    )

    seen_folders = set()

    for name in translated_files:
        if len(name) < 7 or name[5] != '_':
            raise RuntimeError(
                f'Unexpected translated SCED filename: {name}'
            )

        folder = name[:5]

        if folder in seen_folders:
            raise RuntimeError(
                f'Multiple translated SCED files map to '
                f'{folder}.scpk'
            )

        seen_folders.add(folder)

        translated_sced = os.path.join(
            'SCED_NEW',
            name
        )

        source_folder = os.path.join(
            'SCPK',
            folder
        )

        if not os.path.isdir(source_folder):
            print(
                f'Warning: source SCPK folder not found: '
                f'{source_folder}'
            )
            continue

        members = [
            filename
            for filename in os.listdir(source_folder)
            if os.path.isfile(
                os.path.join(source_folder, filename)
            )
        ]

        try:
            members.sort(
                key=lambda filename: int(
                    os.path.splitext(filename)[0]
                )
            )
        except ValueError as exc:
            raise RuntimeError(
                f'{folder}: SCPK contains a non-numeric '
                f'filename: {members}'
            ) from exc

        sced_members = [
            filename
            for filename in members
            if filename.lower().endswith('.sced')
        ]

        if len(sced_members) != 1:
            raise RuntimeError(
                f'{folder}: expected exactly one SCED member, '
                f'but found {len(sced_members)}: '
                f'{sced_members}'
            )

        source_sced_name = sced_members[0]

        if members[-1] != source_sced_name:
            raise RuntimeError(
                f'{folder}: SCED is not the final numerical '
                f'member. Final member: {members[-1]}, '
                f'SCED member: {source_sced_name}'
            )

        sizes = []
        packed_data = bytearray()

        for filename in members:
            source_file = os.path.join(
                source_folder,
                filename
            )

            member_index = str(
                int(os.path.splitext(filename)[0])
            )

            try:
                compression_type = json_data[
                    folder
                ][member_index]
            except KeyError as exc:
                raise RuntimeError(
                    f'{folder}: missing compression '
                    f'information for member {member_index}'
                ) from exc

            if filename == source_sced_name:
                if compression_type != 0:
                    compressed_file = translated_sced + '.c'

                    if os.path.exists(compressed_file):
                        os.remove(compressed_file)

                    compress_comptoe(
                        translated_sced,
                        compression_type
                    )

                    if not os.path.isfile(compressed_file):
                        raise RuntimeError(
                            f'Compression failed for '
                            f'{translated_sced}: '
                            f'{compressed_file} was not created'
                        )

                    validate_comptoe_roundtrip(
                        translated_sced,
                        compressed_file
                    )

                    with open(
                        compressed_file,
                        'rb'
                    ) as input_file:
                        member_data = input_file.read()

                    os.remove(compressed_file)
                else:
                    with open(
                        translated_sced,
                        'rb'
                    ) as input_file:
                        member_data = input_file.read()
            else:
                with open(
                    source_file,
                    'rb'
                ) as input_file:
                    member_data = input_file.read()

            packed_data += member_data
            sizes.append(len(member_data))

        header_file = os.path.join(
            'SCPK_HEADERS',
            f'{folder}.bin'
        )

        if not os.path.isfile(header_file):
            raise RuntimeError(
                f'{folder}: original SCPK header not found: '
                f'{header_file}. Run Unpack SCPK again '
                f'using the original Japanese FILE.FPB.'
            )

        with open(header_file, 'rb') as input_file:
            original_header = bytearray(input_file.read())

        if len(original_header) != 16:
            raise RuntimeError(
                f'{folder}: invalid saved SCPK header size: '
                f'{len(original_header)}'
            )

        if original_header[:4] != b'SCPK':
            raise RuntimeError(
                f'{folder}: invalid saved SCPK signature'
            )

        struct.pack_into(
            '<L',
            original_header,
            8,
            len(sizes)
        )

        output_file = os.path.join(
            'SCPK_PACKED',
            f'{folder}.scpk'
        )

        with open(output_file, 'wb') as output:
            output.write(original_header)

            for member_size in sizes:
                output.write(
                    struct.pack('<L', member_size)
                )

            output.write(packed_data)

        expected_size = (
            16
            + len(sizes) * 4
            + sum(sizes)
        )

        actual_size = os.path.getsize(output_file)

        if actual_size != expected_size:
            raise RuntimeError(
                f'{folder}: rebuilt SCPK has the wrong size. '
                f'Expected {expected_size}, got {actual_size}.'
            )

        print(
            f'Packed {output_file}: '
            f'{len(members)} members, '
            f'{len(packed_data)} data bytes'
        )


def move_scpk_packed():
    for f in os.listdir('SCPK_PACKED'):
        shutil.copy(os.path.join('SCPK_PACKED', f), 'FPB/' + f)

def move_pak1_packed():
    for f in os.listdir('PAK1_PACKED'):
        shutil.copy(os.path.join('PAK1_PACKED', f), 'FPB/' + f)

def verify_packed_fpb(
    fpb_path,
    packed_sources,
    start_offsets,
    remainders,
    expected_total_size
):
    chunk_size = 1024 * 1024

    actual_total_size = os.path.getsize(fpb_path)

    if actual_total_size != expected_total_size:
        raise RuntimeError(
            f'{fpb_path}: wrong total size. '
            f'Expected {expected_total_size}, '
            f'got {actual_total_size}.'
        )

    with open(fpb_path, 'rb') as packed_file:
        for index, (
            key,
            extension,
            source_path,
            source_size
        ) in enumerate(packed_sources):
            if extension == 'dummy':
                continue

            packed_file.seek(start_offsets[index])

            with open(source_path, 'rb') as source_file:
                remaining = source_size

                while remaining:
                    amount = min(chunk_size, remaining)
                    expected = source_file.read(amount)
                    actual = packed_file.read(amount)

                    if actual != expected:
                        raise RuntimeError(
                            f'FILE_NEW.FPB verification failed '
                            f'for entry {key}.{extension}'
                        )

                    remaining -= len(expected)

            padding = packed_file.read(remainders[index])

            if padding != b'\x00' * remainders[index]:
                raise RuntimeError(
                    f'FILE_NEW.FPB contains non-zero padding '
                    f'after entry {key}.{extension}'
                )


def pack_fpb():
    move_scpk_packed()

    if os.path.isdir('PAK1_PACKED'):
        move_pak1_packed()

    with open('FPB.json', 'r', encoding='utf-8') as json_file:
        json_data = json.load(json_file)

    try:
        entries = sorted(
            json_data.items(),
            key=lambda item: int(item[0])
        )
    except ValueError as exc:
        raise RuntimeError(
            'FPB.json contains a non-numeric entry index'
        ) from exc

    actual_indices = [
        int(key)
        for key, _value in entries
    ]

    expected_indices = list(range(len(entries)))

    if actual_indices != expected_indices:
        raise RuntimeError(
            'FPB.json indices are not continuous.\n'
            f'Found:    {actual_indices}\n'
            f'Expected: {expected_indices}'
        )

    original_pointer_count = len(get_pointers())

    if len(entries) + 1 != original_pointer_count:
        raise RuntimeError(
            'FPB entry/pointer count mismatch.\n'
            f'FPB.json entries: {len(entries)}\n'
            f'SLPS pointers:    {original_pointer_count}\n'
            'Expected one final end pointer after all entries.'
        )

    start_offsets = []
    remainders = []
    packed_sources = []
    buffer = 0

    with open('FILE_NEW.FPB', 'wb') as output:
        for key, extension in entries:
            start_offsets.append(buffer)

            if extension == 'dummy':
                source_path = None
                source_size = 0
                remainder = 0
            else:
                source_path = os.path.join(
                    'FPB',
                    f'{key}.{extension}'
                )

                if not os.path.isfile(source_path):
                    raise RuntimeError(
                        f'Missing FPB source entry: {source_path}'
                    )

                source_size = os.path.getsize(source_path)

                with open(source_path, 'rb') as input_file:
                    shutil.copyfileobj(
                        input_file,
                        output,
                        length=1024 * 1024
                    )

                remainder = (-source_size) % 0x40
                output.write(b'\x00' * remainder)

            if buffer & low_bits:
                raise RuntimeError(
                    f'FPB entry {key} starts at an '
                    f'unaligned offset: 0x{buffer:X}'
                )

            if remainder > low_bits:
                raise RuntimeError(
                    f'FPB entry {key} has an invalid '
                    f'remainder: {remainder}'
                )

            packed_sources.append(
                (
                    key,
                    extension,
                    source_path,
                    source_size
                )
            )

            remainders.append(remainder)
            buffer += source_size + remainder

    if buffer & low_bits:
        raise RuntimeError(
            f'FILE_NEW.FPB ends at an unaligned '
            f'offset: 0x{buffer:X}'
        )

    pointers = [
        start_offsets[index] | remainders[index]
        for index in range(len(entries))
    ]

    # The extractor needs one extra pointer to mark the end of
    # the final FPB entry. The old packer left this pointer stale.
    pointers.append(buffer)

    copyfile(
        'SLPS_251.72',
        'new_SLPS_251.72'
    )

    with open('new_SLPS_251.72', 'r+b') as executable:
        executable.seek(pointer_begin)

        for pointer in pointers:
            if pointer > 0xFFFFFFFF:
                raise RuntimeError(
                    f'FPB pointer exceeds 32-bit range: '
                    f'0x{pointer:X}'
                )

            executable.write(
                struct.pack('<L', pointer)
            )

        executable.seek(pointer_begin)

        written_pointers = [
            struct.unpack('<L', executable.read(4))[0]
            for _ in pointers
        ]

    if written_pointers != pointers:
        raise RuntimeError(
            'new_SLPS_251.72 pointer verification failed'
        )

    verify_packed_fpb(
        'FILE_NEW.FPB',
        packed_sources,
        start_offsets,
        remainders,
        buffer
    )

    print(
        f'Packed FILE_NEW.FPB: '
        f'{len(entries)} entries, '
        f'{buffer} bytes, '
        f'{len(pointers)} pointers verified'
    )


def insert_font():
    offset = 0xCA238
    size = 0x5518
    elf = open('new_SLPS_251.72' , 'r+b')
    font = open('font.bin', 'rb')
    data = font.read()
    font.close()
    elf.seek(offset, 0)
    if len(data) > size:
        print("Error. Size is greater than allowed.")
        return
    remainder = size - len(data)
    elf.write(data)
    elf.write(b'\x00' * remainder)
    elf.seek(0xC9D41, 0)
    for i in range(0x31, 0x4B):
        elf.write(struct.pack('B', i))
    elf.close()
    #print ("Font inserted")

def export_tbl():
    json_file = open('TBL.json', 'r')
    table = json.load(json_file)
    json_file.close()
    f = open('tod2.tbl', 'w', encoding = 'utf8')
    for k, v in table.items():
        f.write('%04X=%s\n' % (int(k), v))

# folders that will be decompressed
compressed = ['bin', 'mcd', 'pak0', 'pak1', 'pak4', 'tm2']

def is_compressed(name):
    f = open(name, 'rb')
    data = f.read()
    if struct.unpack('<L', data[1:5])[0] == len(data) - 9:
        f.close()
        return [True, data[0]]
    f.close()
    return [False, 0]

def unpack():
    json_file = open('FPB.json', 'r')
    data = json.load(json_file)
    json_file.close()
    c_json = open('compression.json', 'w')
    c_data = {}
    
    try: os.mkdir('FILE')
    except: pass

    for d in data.values():
        if d == 'dummy':
            continue
        try: os.mkdir('FILE/' + d)
        except: pass
    
    for name in os.listdir('FPB'):
        fname = name.split('.')[0]
        if fname in data.keys():
            #print (name)
            new_location = f'FILE/{data[fname]}/{fname}.{data[fname]}'
            #new_location = 'file/' + data[fname] + '/' + fname + '.' + data[fname]
            shutil.copy(os.path.join('FPB/', name), new_location)
            c_result = is_compressed(new_location)
            c_data[fname] = c_result[1]
            if data[fname] in compressed:
                if not c_result[0]:
                    continue
                dec = new_location + '.d'
                subprocess.run(['comptoe.exe', '-d', new_location, dec], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
                os.remove(new_location)
                os.rename(dec, new_location)
    json.dump(c_data, c_json, indent=4)

# True to automatically compress after packing
# False to only pack
compress = True

def extract_pak1():
    os.chdir('FILE')
    #print ("Extracting pak1...")
    for name in os.listdir('pak1'):
        if not name.endswith('pak1'):
            continue
        f = open('pak1/' + name, 'rb')
        try: os.mkdir('pak1/' + name[:5])
        except: pass
        n = struct.unpack('<I', f.read(4))[0]
        offsets = []
        sizes = []
        for i in range(n):
            offsets.append(struct.unpack('<I', f.read(4))[0])
            sizes.append(struct.unpack('<I', f.read(4))[0])
        for i in range(n):
            f.seek(offsets[i], 0)
            data = f.read(sizes[i])
            ext = 'bin'
            if len(data) > 4:
                if data[:4] == b'TM2@':
                    ext = 'tm2'
                elif data[:4] == b'SCED':
                    ext = 'sced'
                else:
                    pass
            o = open('PAK1/' + name[:5] + '/' + '%s_%02d.%s' % (name[:5], i, ext), 'wb')
            o.write(data)
            o.close()
        f.close()
    os.chdir('..')

def move_skits_out():

    os.chdir('FILE/pak1')

    try:
        os.mkdir('SCED')
    except:
        pass
    
    for folder in os.listdir(os.getcwd()):
        if not os.path.isdir(folder):
            continue
        if folder == 'pak1' or folder == '00022':
            continue
        for n in os.listdir(folder):
            if n.endswith('sced'):
                f = n
                break
        new_name = '%s_%s.sced' % (folder, f.split('.')[0])
        try:
            shutil.copy(os.path.join(folder,f), 'SCED/' + f)
        except:
            pass
        #print (new_name)

    os.chdir('../..')

def extract_skit():
    copyfile('TBL.json', 'FILE/pak1/TBL.json')
    os.chdir('FILE/pak1')
    extract_sced_skit()
    os.chdir('../..')
    
def insert_skit():
    os.chdir('FILE/pak1')
    insert_sced()
    os.chdir('../..')
    
def move_skits_in():
    os.chdir('FILE/pak1')
    
    for name in os.listdir('SCED_NEW'):
        folder = name.split('_')[0]
        #n = name.split('_')[0]
        shutil.copy(os.path.join('SCED_NEW/', name), os.path.join(folder, name))
        #print (name)

    os.chdir('../..')

def insert_pak1():
    with open('compression.json', 'r', encoding='utf-8') as json_file:
        json_data = json.load(json_file)

    os.makedirs('PAK1_PACKED', exist_ok=True)

    excluded_folders = {
        'SCED',
        'SCED_NEW',
        'TXT',
        'TXT_EN'
    }

    pak1_root = os.path.join('FILE', 'pak1')

    def get_member_index(filename):
        """
        Expected extracted filename format:
            00023_00.bin
            00023_01.tm2
            00023_02.sced
        """
        stem = os.path.splitext(filename)[0]

        try:
            return int(stem.rsplit('_', 1)[1])
        except (IndexError, ValueError) as exc:
            raise RuntimeError(
                f'Cannot determine PAK1 member index from: {filename}'
            ) from exc

    for name in sorted(os.listdir(pak1_root)):
        folder_path = os.path.join(pak1_root, name)

        if not os.path.isdir(folder_path):
            continue

        if name in excluded_folders:
            continue

        members = [
            filename
            for filename in os.listdir(folder_path)
            if os.path.isfile(os.path.join(folder_path, filename))
        ]

        # Preserve the original internal PAK1 member order.
        members.sort(key=get_member_index)

        if not members:
            print(f'Warning: skipping empty PAK1 directory: {folder_path}')
            continue

        # Validate that extracted indexes form a continuous sequence.
        indexes = [get_member_index(filename) for filename in members]
        expected_indexes = list(range(len(members)))

        if indexes != expected_indexes:
            raise RuntimeError(
                f'{name}: unexpected PAK1 member indexes.\n'
                f'Found:    {indexes}\n'
                f'Expected: {expected_indexes}'
            )

        files = []
        paddings = []

        for filename in members:
            member_path = os.path.join(folder_path, filename)

            with open(member_path, 'rb') as member_file:
                member_data = member_file.read()

            padding = (-len(member_data)) % 16

            files.append(member_data)
            paddings.append(padding)

        member_count = len(files)
        output_path = os.path.join(
            'PAK1_PACKED',
            f'{name}.pak1'
        )

        with open(output_path, 'wb') as output:
            output.write(struct.pack('<I', member_count))

            first_data_offset = 4 + member_count * 8
            header_padding = (-first_data_offset) % 16
            next_offset = first_data_offset + header_padding

            # Write offset and size table.
            for index in range(member_count):
                output.write(struct.pack('<I', next_offset))
                output.write(struct.pack('<I', len(files[index])))

                next_offset += (
                    len(files[index]) +
                    paddings[index]
                )

            output.write(b'\x00' * header_padding)

            # Write files in original numerical order.
            for index in range(member_count):
                output.write(files[index])
                output.write(b'\x00' * paddings[index])

        compression_type = json_data.get(name, 0)

        if compress and compression_type == 3:
            compressed_path = output_path + '.c'

            if os.path.exists(compressed_path):
                os.remove(compressed_path)

            subprocess.run(
                [
                    'comptoe.exe',
                    '-c3',
                    output_path,
                    compressed_path
                ],
                check=True,
                stderr=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW
            )

            os.replace(compressed_path, output_path)

        print(
            f'Packed {output_path}: '
            f'{member_count} members in numerical order'
        )

def donothing():
   filewin = Toplevel(window)
   button = Button(filewin, text="Do nothing button")
   button.pack()

def about():
   about_win = Toplevel(window)

   about_win.title("About PyTOD2 v0.3")
   
   frame0 = LabelFrame(about_win, text="PyTOD2 v0.3", padx=5, pady=5)
   frame0.pack(padx=10, pady=10)
   
   about_label = Label(frame0, text = "PyTOD2 is an open-source tool that can unpack and repack resources from Tales of Destiny 2 (PS2).")
   about_label.pack()

   link1 = Label(frame0, text="GitHub Project", fg="blue", cursor="hand2")
   link1.pack(anchor=W)
   link1.bind("<Button-1>", lambda e: callback("https://github.com/pnvnd/Tales-of-Destiny-2"))

   link2 = Label(frame0, text="Discord Server", fg="blue", cursor="hand2")
   link2.pack(anchor=W)
   link2.bind("<Button-1>", lambda e: callback("https://discord.gg/HZ2NFjpedn"))

   close_button = Button(about_win, text="Close", command = about_win.destroy)
   close_button.pack(padx=10, pady=10)

def work_dir():
    pwd = filedialog.askdirectory()
    os.chdir(pwd)
    cwd.config(text="Current Working Directory: " + pwd)

"""
Graphical Interface Start
"""

window = Tk()
window.resizable(False, False)
window.title("PyTOD2 - Tales of Destiny 2 (PS2) Tool")

menubar = Menu(window)
filemenu = Menu(menubar, tearoff=0)
filemenu.add_command(label="Change Work Directory", command=work_dir)

filemenu.add_separator()

filemenu.add_command(label="Exit", command=window.destroy)
menubar.add_cascade(label="File", menu=filemenu)
editmenu = Menu(menubar, tearoff=0)
editmenu.add_command(label="Undo", command=donothing)

helpmenu = Menu(menubar, tearoff=0)
helpmenu.add_command(label="About", command=about)
menubar.add_cascade(label="Help", menu=helpmenu)

window.config(menu=menubar)

#window.iconbitmap("favicon.ico")
label = Label(window, text = "PyTOD2 unpacks resources from Tales of Destiny 2 (PS2) and repacks them.")
#label.pack(padx = 200, pady = 50)
label.grid(row=0, column=0, columnspan=4)


#path_SLPS = Label(window, text = "Path to SLPS_251.72")
#path_SLPS.pack(anchor="w")


frame1 = LabelFrame(window, text="Unpack", padx=5, pady=5)
frame1.grid(row=1, column=0, padx=10, pady=10)

btn_unpackFPB = Button(frame1, text="Unpack FPB", command = extract_fpb)
btn_unpackFPB.grid(row=0, column=0, sticky='news')

btn_unpackSCPK = Button(frame1, text="Unpack SCPK", command = extract_scpk)
btn_unpackSCPK.grid(row=1, column=0, sticky='news')

btn_unpackSCED = Button(frame1, text="Unpack SCED", command = extract_sced)
btn_unpackSCED.grid(row=2, column=0, sticky='news')

btn_unpackPAK1 = Button(frame1, text="Unpack PAK1", command = extract_pak1)
btn_unpackPAK1.grid(row=3, column=0, sticky='news')

btn_moveOUT = Button(frame1, text="Move Skits OUT", command = move_skits_out)
btn_moveOUT.grid(row=4, column=0, sticky='news')

btn_unpackSKIT = Button(frame1, text="Extract SKIT", command = extract_skit)
btn_unpackSKIT.grid(row=5, column=0, sticky='news')

frame2 = LabelFrame(window, text="Re-pack", padx=5, pady=5)
frame2.grid(row=1, column=1, padx=10, pady=10)

btn_packFPB = Button(frame2, text="Pack FPB", command = pack_fpb)
btn_packFPB.grid(row=0, column=0, sticky='news')

btn_packSCPK = Button(frame2, text="Pack SCPK", command = pack_scpk)
btn_packSCPK.grid(row=1, column=0, sticky='news')

btn_packSCED = Button(frame2, text="Pack SCED", command = insert_sced)
btn_packSCED.grid(row=2, column=0, sticky='news')

btn_packPAK1 = Button(frame2, text="Pack PAK1", command = insert_pak1)
btn_packPAK1.grid(row=3, column=0, sticky='news')

btn_moveIN = Button(frame2, text="Move Skits IN", command = move_skits_in)
btn_moveIN.grid(row=4, column=0, sticky='news')

btn_packSKIT = Button(frame2, text="Insert SKIT", command = insert_skit)
btn_packSKIT.grid(row=5, column=0, sticky='news')

frame3 = LabelFrame(window, text="Misc.", padx=5, pady=5)
frame3.grid(row=1, column=2, padx=10, pady=10)

btn_sortFPB = Button(frame3, text="Organize FPB", command = unpack)
btn_sortFPB.grid(row=0, column=0, sticky='news')

btn_unpackMOVIE = Button(frame3, text="Unpack MOVIE", command = extract_movie)
btn_unpackMOVIE.grid(row=1, column=0, sticky='news')

btn_insertFONT = Button(frame3, text="Insert FONT", command = insert_font)
btn_insertFONT.grid(row=2, column=0, sticky='news')

btn_exportTBL = Button(frame3, text="Export TBL", command = export_tbl)
btn_exportTBL.grid(row=3, column=0, sticky='news')

btn_pak1skit = Button(frame3, text="Pack Movie (Broken)")
btn_pak1skit.grid(row=4, column=0, sticky='news')

btn_getPWD = Button(frame3, text="Random Button", command = donothing)
btn_getPWD.grid(row=5, column=0, sticky='news')

#Set working directory for GUI
cwd = Label(window, text = "Current Working Directory: " + os.getcwd(), bd=1, relief=SUNKEN, anchor=W)
cwd.grid(row=5, column=0, columnspan=4, sticky='news')



window.mainloop()



'''
def tog():
    if window.cget("bg") == "black":
        window.configure(bg="gray")
    else:
        window.configure(bg="black")

btn_tog = Button(window, text="Dark Mode", command=tog)
btn_tog.pack(padx = 200, pady = 10)

def dialog():
    var= box.askyesno("Message Box", "Proceed?")
    if var == 1:
        box.showinfo("Yes Box", "Proceeding...")
    else:
        box.showwarning("No Box", "Cancelling...")

btn = Button(window, text="Click", command=dialog)
btn.pack(padx = 150, pady = 50)

#btn_end = Button(window, text="Close", command=exit)
#btn_end.pack(anchor="se")
    #padx = 150, pady = 20
'''




