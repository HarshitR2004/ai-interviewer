import json
import sys

from backend.common.errors import InvalidInput

from .pdf_validation import _INVALID, MAX_PDF_BYTES, _extract_checked


def main() -> None:
    if sys.platform != "win32":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
    try:
        payload = {"text": _extract_checked(sys.stdin.buffer.read(MAX_PDF_BYTES + 1))}
    except InvalidInput as exc:
        payload = {"error": str(exc)}
    except Exception:
        payload = {"error": _INVALID}
    sys.stdout.buffer.write(json.dumps(payload).encode("utf-8"))


if __name__ == "__main__" and sys.argv[1:] == ["--worker"]:
    main()
