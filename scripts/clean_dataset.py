"""Удалить из CSV строки с пропущенными значениями без изменения остальных строк."""

import argparse
import csv
import os
import tempfile
from pathlib import Path


def drop_incomplete_rows(path: Path) -> tuple[int, int]:
    """Атомарно заменить CSV очищенной версией и вернуть числа входных и выходных строк."""
    source_rows = 0
    kept_rows = 0

    # Временный файл находится рядом с исходным, поэтому os.replace остаётся атомарным.
    with path.open(encoding="utf-8", newline="") as source:
        header_line = source.readline()
        header = next(csv.reader([header_line]))

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            delete=False,
        ) as target:
            temporary_path = Path(target.name)
            target.write(header_line)

            for line_number, line in enumerate(source, start=2):
                source_rows += 1
                row = next(csv.reader([line]))
                if len(row) != len(header):
                    temporary_path.unlink(missing_ok=True)
                    raise ValueError(f"строка {line_number}: ожидалось {len(header)} полей, получено {len(row)}")

                # Пустая CSV-ячейка становится пустой строкой; такие записи исключаем целиком.
                if any(value == "" for value in row):
                    continue

                target.write(line)
                kept_rows += 1

    os.replace(temporary_path, path)
    return source_rows, kept_rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="путь к очищаемому CSV")
    args = parser.parse_args()

    source_rows, kept_rows = drop_incomplete_rows(args.path)
    print(f"rows before: {source_rows}")
    print(f"rows after: {kept_rows}")
    print(f"rows removed: {source_rows - kept_rows}")


if __name__ == "__main__":
    main()
