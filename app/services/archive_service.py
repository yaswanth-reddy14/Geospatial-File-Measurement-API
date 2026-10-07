import re
import stat
import zipfile
import zlib
from pathlib import Path, PurePosixPath

from app.core.config import Settings
from app.core.exceptions import InvalidGeospatialFileError

REQUIRED_COMPONENTS = {".shp", ".shx", ".dbf", ".prj"}
ALLOWED_COMPONENTS = REQUIRED_COMPONENTS | {".cpg"}


def extract_shapefile(archive_path: Path, destination: Path, settings: Settings) -> Path:
    """Validate every entry, then extract only the selected dataset's safe components."""
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            if not members or len(members) > settings.max_archive_members:
                raise InvalidGeospatialFileError("Archive is empty or has too many entries.")
            paths: dict[str, zipfile.ZipInfo] = {}
            total_size = 0
            for member in members:
                path = PurePosixPath(member.filename.replace("\\", "/"))
                mode = member.external_attr >> 16
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or re.search(r"[:\x00-\x1f]", member.filename)
                    or stat.S_ISLNK(mode)
                    or (member.flag_bits & 1)
                ):
                    raise InvalidGeospatialFileError("Unsafe or encrypted archive entry.")
                key = str(path).casefold()
                if key in paths:
                    raise InvalidGeospatialFileError("Archive contains duplicate entry names.")
                paths[key] = member
                total_size += member.file_size
                if total_size > settings.max_archive_bytes:
                    raise InvalidGeospatialFileError("Archive exceeds the expansion size limit.")
                if member.file_size / max(member.compress_size, 1) > settings.max_compression_ratio:
                    raise InvalidGeospatialFileError("Archive compression ratio exceeds the limit.")

            candidates = [
                key for key, item in paths.items() if key.endswith(".shp") and not item.is_dir()
            ]
            if len(candidates) != 1:
                raise InvalidGeospatialFileError(
                    "Archive must contain exactly one Shapefile dataset."
                )
            stem = candidates[0][:-4]
            missing = sorted(ext for ext in REQUIRED_COMPONENTS if stem + ext not in paths)
            if missing:
                raise InvalidGeospatialFileError(
                    "Missing Shapefile components: " + ", ".join(missing) + "."
                )
            destination.mkdir(parents=True, exist_ok=True)
            actual_size = 0
            for extension in sorted(ALLOWED_COMPONENTS):
                member = paths.get(stem + extension)
                if member is None:
                    continue
                if member.is_dir() or member.file_size == 0:
                    raise InvalidGeospatialFileError("Shapefile components must be nonempty files.")
                # Fixed names avoid platform-specific filenames and untrusted sidecar drivers.
                target = destination / ("dataset" + extension)
                with archive.open(member) as source, target.open("wb") as output:
                    written = 0
                    while chunk := source.read(64 * 1024):
                        written += len(chunk)
                        actual_size += len(chunk)
                        if actual_size > settings.max_archive_bytes or written > member.file_size:
                            raise InvalidGeospatialFileError("Archive exceeds the expansion limit.")
                        output.write(chunk)
            return destination / "dataset.shp"
    except (
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
        RuntimeError,
        NotImplementedError,
        zlib.error,
    ) as exc:
        raise InvalidGeospatialFileError("Invalid or corrupted ZIP archive.") from exc
