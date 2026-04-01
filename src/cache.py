# src/cache.py
import datetime
import functools

_cache = {}

def cached(key, ttl=180):
    def decorator(func):
        def wrapper(*args, **kwargs):
            now = datetime.datetime.now().timestamp()
            if key in _cache and now - _cache[key]['ts'] < ttl:
                return _cache[key]['val']
            result = func(*args, **kwargs)
            _cache[key] = {'val': result, 'ts': now}
            return result
        return wrapper
    return decorator

def cached_with_key(key_func, ttl=180):
    """
    Dekorator cache z kluczem generowanym dynamicznie na podstawie argumentów funkcji.
    key_func – funkcja, która przyjmuje te same argumenty co dekorowana funkcja i zwraca string.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            key = key_func(*args, **kwargs)
            now = datetime.datetime.now().timestamp()
            if key in _cache and now - _cache[key]['ts'] < ttl:
                return _cache[key]['val']
            result = func(*args, **kwargs)
            _cache[key] = {'val': result, 'ts': now}
            return result
        return wrapper
    return decorator