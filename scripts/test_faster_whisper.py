import sys
from pathlib import Path

vendor_path = Path(__file__).resolve().parent.parent / ".vendor"
if str(vendor_path) not in sys.path:
    sys.path.insert(0, str(vendor_path))

from faster_whisper import WhisperModel


def main() -> None:
    model = WhisperModel("tiny", device="cpu", compute_type="int8")
    print("faster-whisper model initialized successfully")


if __name__ == "__main__":
    main()
