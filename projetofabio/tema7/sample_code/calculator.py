# sample_code/calculator.py
# Arquivo de exemplo para testar o pipeline.
# Faça upload para S3 com: bash scripts/upload_repo.sh sample_code/

def add(a, b):
    return a + b

def subtract(a, b):
    return a - b

def divide(a, b):
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b

def factorial(n):
    if n < 0:
        raise ValueError("n must be non-negative")
    if n == 0:
        return 1
    result = 1
    for i in range(1, n + 1):
        result *= i
    return result

def find_max(numbers):
    if not numbers:
        return None
    m = numbers[0]
    for x in numbers[1:]:
        if x > m:
            m = x
    return m
