import datetime

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