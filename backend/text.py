import re
import unicodedata

EN_DIGITS = 'zero one two three four five six seven eight nine'.split()
HI_DIGITS = 'शून्य एक दो तीन चार पाँच छह सात आठ नौ'.split()
EN_SMALL = EN_DIGITS + 'ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split()
EN_TENS = ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety']


def number_words(token, language):
    digits = HI_DIGITS if language == 'hi' else EN_DIGITS
    # Basic Hindi reads digits individually; no false claim of full numeric grammar.
    if language == 'hi' or len(token) > 3 or (len(token) > 1 and token[0] == '0'):
        return ' '.join(digits[int(c)] for c in token)
    n = int(token)
    if n < 20:
        return EN_SMALL[n]
    if n < 100:
        return EN_TENS[n // 10] + (' ' + EN_SMALL[n % 10] if n % 10 else '')
    return EN_SMALL[n // 100] + ' hundred' + (' ' + number_words(str(n % 100), language) if n % 100 else '')


def normalize_text(text, language):
    text = unicodedata.normalize('NFKC', text)
    text = ''.join(str(unicodedata.decimal(c)) if c.isdecimal() else c for c in text)
    replacements = {'Dr.': 'डॉक्टर', 'Mr.': 'श्री', 'Mrs.': 'श्रीमती', 'डॉ.': 'डॉक्टर'} if language == 'hi' else {'Dr.': 'Doctor', 'Mr.': 'Mister', 'Mrs.': 'Missus', 'e.g.': 'for example', 'i.e.': 'that is'}
    for short, full in replacements.items():
        text = re.sub(r'(?<!\w)' + re.escape(short) + r'(?=\s|$)', full, text, flags=re.I)
    text = re.sub(r'\d+', lambda match: number_words(match.group(), language), text)
    return re.sub(r'\s+', ' ', text).strip()


def chunk_text(text, max_chars=250):
    if max_chars < 1:
        raise ValueError('max_chars must be positive')
    sentences = re.split(r'(?<=[.!?।])\s+', text.strip())
    chunks, current = [], ''
    for sentence in sentences:
        # Split overlong sentences at whitespace, then hard-split overlong tokens.
        pieces = []
        while len(sentence) > max_chars:
            cut = sentence.rfind(' ', 0, max_chars + 1)
            if cut <= 0:
                cut = max_chars
            pieces.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if sentence:
            pieces.append(sentence)
        for piece in pieces:
            candidate = (current + ' ' + piece).strip()
            if current and len(candidate) > max_chars:
                chunks.append(current)
                current = piece
            else:
                current = candidate
    if current:
        chunks.append(current)
    return chunks
