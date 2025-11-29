from langdetect import detect, detect_langs

# Simple test
print(detect("This is a test sentence."))   # expected: 'en'
print(detect("C'est une belle journée."))   # expected: 'fr'
print(detect("Livet är bättre än när de var fattiga bönder"))   # expected: 'sv'
print(detect("这是一个测试。"))              # expected: 'zh-cn' or 'zh'

# See multiple probabilities
print(detect_langs("Esta es una prueba."))
