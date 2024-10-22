import os
import sys
import lzma
from pathlib import Path
from PySquashfsImage import SquashFsImage
from enum import IntEnum

class Compression(IntEnum):
    NO = 0
    ZLIB = 1
    LZMA = 2
    LZO = 3
    XZ = 4
    LZ4 = 5
    ZSTD = 6

class Firmware:
    def __init__(self, firmware_path):
        self.firmware_path = firmware_path
        self.output_dir = Path("extracted_firmware")
        self.output_dir.mkdir(exist_ok=True)
        self._log("Created output directory", str(self.output_dir))

    def _log(self, title, value="", level="info"):
        symbols = {"info": "[*]", "success": "[+]", "error": "[!]"}
        print(f"{symbols.get(level)} {title}: {value}" if value else f"{symbols.get(level)} {title}")

    def print_superblock_info(self, superblock):
        log = self._log
        log(f"{'-'*40}")
        log(f"Superblock Information:")
        log(f"{'-'*40}")
        log(f"{'Magic:':<25}0x{superblock.s_magic:X}")
        log(f"{'Filesystem Size:':<25}{superblock.bytes_used} bytes")
        log(f"{'Compression:':<25}{Compression(superblock.compression).name}")
        log(f"{'Block Size:':<25}{superblock.block_size}")
        log(f"{'Number of Inodes:':<25}{superblock.inodes}")
        log(f"{'Number of Fragments:':<25}{superblock.fragments}")
        log(f"{'Inode Table Start:':<25}0x{superblock.inode_table_start:X}")
        log(f"{'Directory Table Start:':<25}0x{superblock.directory_table_start:X}")
        log(f"{'Fragment Table Start:':<25}0x{superblock.fragment_table_start:X}")
        log(f"{'ID Table Start:':<25}0x{superblock.id_table_start:X}")
        log(f"{'xattr Table Start:':<25}0x{superblock.xattr_id_table_start:X}")
        log(f"{'-'*40}")

    def extract_lzma_section(self, firmware_data, offset, dictionary_size, uncompressed_size):
        """Extract LZMA compressed section from firmware."""
        self._log("Attempting to extract LZMA section", f"Offset: {offset}, Dictionary size: {dictionary_size}, Expected uncompressed size: {uncompressed_size}")

        for test_offset in [offset, offset - 1, offset + 1, offset - 13, offset + 13]:
            try:
                self._log("Trying offset", str(test_offset))
                lzma_data = firmware_data[test_offset:]
                filters = [{"id": lzma.FILTER_LZMA1, "dict_size": dictionary_size}]
                decompressor = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=filters)
                decompressed_data = decompressor.decompress(lzma_data)

                if decompressed_data:
                    self._log("Successfully decompressed", f"{len(decompressed_data)} bytes at offset {test_offset}", "success")
                    return decompressed_data
            except Exception:
                continue

        self._log("Could not find valid LZMA data around specified offset", level="error")
        return None

    def extract_squashfs_section(self, firmware_data, offset, size):
        """Extract SquashFS filesystem section."""
        self._log("Extracting SquashFS section", f"Offset: {offset}, Size: {size}")
        return firmware_data[offset:offset + size]

    def extract_squashfs_contents(self, squashfs_path):
        """Extract contents of SquashFS filesystem."""
        try:
            self._log("Attempting to extract SquashFS contents", str(squashfs_path))
            extract_dir = self.output_dir / "squashfs_contents"
            extract_dir.mkdir(exist_ok=True)

            self._log("Opening SquashFS image")
            with SquashFsImage.from_file(str(squashfs_path)) as image:
                self._log("SquashFS filesystem information")
                self.print_superblock_info(image.sblk)

                # List and extract all files
                self._log("Extracting files")
                for item in image:
                    relative_path = str(item.path).lstrip('/')
                    target_path = extract_dir / relative_path
                    target_path.parent.mkdir(parents=True, exist_ok=True)

                    if not item.is_dir:
                        self._log("Extracting", str(item.path), "success")
                        if item.is_file:
                            with open(target_path, 'wb') as f:
                                for block in item.iter_bytes():
                                    f.write(block)
                        elif item.is_symlink:
                            self._handle_symlink(item, target_path)

            self._log("SquashFS contents extracted successfully", level="success")
            return True

        except Exception as e:
            self._log(f"Error extracting SquashFS contents: {e}", level="error")
            return False


    def _handle_symlink(self, item, target_path):
        """Handle symbolic links during extraction."""
        try:
            link_target = item.readlink()
            self._log("Creating symlink", f"{item.path} -> {link_target}")
            if target_path.exists():
                target_path.unlink()
            try:
                target_path.symlink_to(link_target)
            except Exception:
                with open(target_path, 'w') as f:
                    f.write(f"Symlink to: {link_target}")
        except Exception as e:
            self._log(f"Error handling symlink {item.path}: {e}", level="error")

    def extract_firmware(self):
        self._log("Starting extraction of firmware", str(self.firmware_path))

        try:
            with open(self.firmware_path, 'rb') as f:
                firmware_data = f.read()
            self._log("Successfully read firmware", f"{len(firmware_data)} bytes", "success")
        except Exception as e:
            self._log(f"Error reading firmware file: {e}", level="error")
            return False

        # Extract LZMA section
        lzma_data = self.extract_lzma_section(firmware_data, 10264, 8388608, 8861280)
        if lzma_data:
            lzma_path = self.output_dir / "extracted_lzma.bin"
            with open(lzma_path, 'wb') as f:
                f.write(lzma_data)
            self._log("LZMA section saved", str(lzma_path), "success")
        else:
            self._log("LZMA extraction failed, continuing with SquashFS extraction", level="error")

        # Extract SquashFS section
        squashfs_data = self.extract_squashfs_section(firmware_data, 2751522, 5159718)
        squashfs_path = self.output_dir / "filesystem.squashfs"
        with open(squashfs_path, 'wb') as f:
            f.write(squashfs_data)
        self._log("SquashFS filesystem saved", str(squashfs_path), "success")

        self.extract_squashfs_contents(squashfs_path)
        self._log("Extraction process completed", level="success")
        return True

def main():
    if len(sys.argv) != 2:
        print("Usage: python main.py <bin>")
        return

    firmware_path = sys.argv[1]
    if not os.path.exists(firmware_path):
        print(f"[!] Firmware file not found: {firmware_path}")
        return

    fw = Firmware(firmware_path)
    fw.extract_firmware()

if __name__ == "__main__":
    main()