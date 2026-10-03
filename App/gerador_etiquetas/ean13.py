"""EAN-13 barcode math: the check digit algorithm and building a full 13-digit
code out of a prefix + sequential product reference. No barcode-drawing here --
that's reportlab's job (see labels_pdf.py); this module is pure digit math so
it's cheap to unit test.
"""


def checksum_digit(payload: str) -> str:
    """payload: the first 12 digits of an EAN-13 code. Returns the 13th
    (check) digit per the standard EAN-13 algorithm: odd positions (1st,
    3rd, ...) weight 1, even positions weight 3, sum mod 10, then the
    distance up to the next multiple of 10 (0 if already a multiple)."""
    if len(payload) != 12 or not payload.isdigit():
        raise ValueError(f"payload precisa ter exatamente 12 dígitos, recebido: {payload!r}")

    total = sum(
        int(digit) * (1 if position % 2 == 0 else 3)
        for position, digit in enumerate(payload)
    )
    return str((10 - (total % 10)) % 10)


def build_ean13(prefix: str, sequence_number: int, sequence_digits: int = 10) -> str:
    """Builds a full 13-digit EAN-13 code: prefix + zero-padded sequence_number
    + check digit. len(prefix) + sequence_digits must equal 12."""
    if sequence_number < 0 or sequence_number >= 10 ** sequence_digits:
        raise ValueError(
            f"sequence_number {sequence_number} não cabe em {sequence_digits} dígitos")

    payload = prefix + str(sequence_number).zfill(sequence_digits)
    if len(payload) != 12:
        raise ValueError(
            f"prefix ({len(prefix)} dígitos) + sequence_digits ({sequence_digits}) "
            f"precisa somar 12, deu {len(payload)}")

    return payload + checksum_digit(payload)
