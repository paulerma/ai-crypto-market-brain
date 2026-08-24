from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')

start_marker = '        tr = trend_info.get("transition")\n'
end_marker = '        fig_fast = trend_chart(chart_simple, selected, timeframe, trend_info)\n'
start = s.find(start_marker)
if start < 0:
    raise RuntimeError('No se encontró el inicio del bloque de señales simples')
end = s.find(end_marker, start)
if end < 0:
    raise RuntimeError('No se encontró el final del bloque de señales simples')

new_block = '''        tr = trend_info.get("transition")
        early = trend_info.get("early_warning")
        active = tr or early
        dirs = trend_info.get("directional_forecasts", {})
        up_fc = dirs.get("SUBIDA")
        down_fc = dirs.get("BAJADA")

        def _compact_timing(fc):
            if not fc or not fc.get("has_window"):
                return "SIN SEÑAL CLARA"
            a = _duration_text(timeframe, int(fc.get("start_bars", 1)))
            b = _duration_text(timeframe, int(fc.get("end_bars", fc.get("start_bars", 1))))
            if a == b:
                return a
            ap = a.split(" ", 1)
            bp = b.split(" ", 1)
            if len(ap) == 2 and len(bp) == 2 and ap[1] == bp[1]:
                return f"{ap[0]}–{bp[0]} {ap[1]}"
            return f"{a}–{b}"

        st.markdown(f"## 🟢 SUBE EN: {_compact_timing(up_fc)}")
        st.markdown(f"## 🔴 BAJA EN: {_compact_timing(down_fc)}")

'''

s = s[:start] + new_block + s[end:]
p.write_text(s, encoding='utf-8')
print('Vista sencilla reducida a SUBE EN / BAJA EN.')
