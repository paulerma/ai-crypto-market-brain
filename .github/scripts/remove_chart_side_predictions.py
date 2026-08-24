from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')

start_marker = '    primary_dir = primary.get("direction")\n'
end_marker = '    if timeframe in ("1m", "2m", "3m", "5m", "10m", "15m"):\n'
start = s.find(start_marker)
if start < 0:
    raise RuntimeError('No se encontró el bloque lateral de predicciones')
end = s.find(end_marker, start)
if end < 0:
    raise RuntimeError('No se encontró el final del bloque lateral de predicciones')

s = s[:start] + s[end:]
p.write_text(s, encoding='utf-8')
print('Bloque lateral eliminado; quedan puntos, precio y SUBE EN / BAJA EN.')
