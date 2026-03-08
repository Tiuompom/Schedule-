import os, subprocess, tempfile
import pandas as pd
import matplotlib
matplotlib.use('Agg')


class ReportingManager:
    def __init__(self, solution, config, base_path, shortage, availability_dict):
        self.solution     = solution
        self.workers_list = sorted(list(set(availability_dict.keys())))
        self.config       = config
        self.base_path    = base_path
        self.availability = availability_dict
        self.s_worker     = shortage['worker']
        self.s_till       = shortage['till']
        self.s_manager    = shortage['manager']
        self.days        = config["structure"]["days"]
        self.time_labels = config["structure"]["time_labels"]
        self.roles       = config["structure"]["roles"]
        self.df_schedule = self.generate_schedule()

    def generate_schedule(self) -> pd.DataFrame:
        rows = []
        for i in self.workers_list:
            row = {"Staff Name": i}
            for idx, day in enumerate(self.days):
                slots = []
                for t in self.time_labels:
                    for role in self.roles:
                        if self.solution[i][idx][t][role].varValue == 1:
                            slots.append(self.time_labels[t])
                row[day] = ", ".join(slots) if slots else "-"
            rows.append(row)
        return pd.DataFrame(rows)

    def save_schedule_toxl(self) -> str:
        path = os.path.join(self.base_path, "outputs", "Weekly_Staff_Schedule.xlsx")
        with pd.ExcelWriter(path, engine='xlsxwriter') as writer:
            self.df_schedule.to_excel(writer, index=False, sheet_name='Staff Schedule')
            wb  = writer.book
            ws  = writer.sheets['Staff Schedule']
            hdr = wb.add_format({'bold': True, 'align': 'center', 'bg_color': '#4F81BD', 'font_color': 'white', 'border': 1, 'locked': True})
            lck = wb.add_format({'bg_color': '#F2F2F2', 'border': 1, 'locked': True})
            edt = wb.add_format({'border': 1, 'locked': False})
            for col, val in enumerate(self.df_schedule.columns):
                ws.write(0, col, val, hdr)
            for row in range(1, len(self.df_schedule) + 1):
                for col in range(len(self.df_schedule.columns)):
                    ws.write(row, col, self.df_schedule.iloc[row-1, col], lck if col == 0 else edt)
            ws.set_column(0, 0, 25)
            ws.set_column(1, len(self.df_schedule.columns)-1, 18)
            ws.protect()
        return path

    def save_schedule_pdf(self) -> None:
        output_dir = os.path.join(self.base_path, "outputs")
        os.makedirs(output_dir, exist_ok=True)
        pdf_file = os.path.join(output_dir, "Weekly_Staff_Schedule.pdf")

        html = self._build_html()

        with tempfile.NamedTemporaryFile(suffix='.html', delete=False, mode='w', encoding='utf-8') as f:
            f.write(html)
            tmp_html = f.name

        try:
            subprocess.run([
                r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe',
                '--orientation', 'Landscape',
                '--page-size', 'A4',
                '--margin-top', '0',
                '--margin-bottom', '0',
                '--margin-left', '0',
                '--margin-right', '0',
                '--encoding', 'UTF-8',
                '--no-outline',
                '--quiet',
                tmp_html, pdf_file
            ], check=True)
        finally:
            os.unlink(tmp_html)

        print(f"✔ PDF saved to: {pdf_file}")

    def _build_html(self) -> str:
        day_cols   = self.days
        day_labels = ["LUN", "MAR", "MER", "JEU", "VEN", "SAM", "DIM"]
        pill_cls   = {"14h": "p14", "18h": "p18", "19h": "p19"}

        df = self.df_schedule.copy()
        df["_count"] = df[day_cols].apply(lambda r: sum(1 for v in r if v and v != "-"), axis=1)
        df = df.sort_values("_count", ascending=False).drop(columns="_count")

        rows_html = ""
        for _, row in df.iterrows():
            total    = sum(1 for d in day_cols if row[d] and row[d] != "-")
            name_cls = "name" if total > 0 else "name off"
            badge    = f'<span class="badge">{total}</span>' if total > 0 else ""
            cells    = ""
            for i, day in enumerate(day_cols):
                val = row[day]
                if val and val != "-":
                    sh  = val.strip().split(",")[0].strip()
                    cls = pill_cls.get(sh, "")
                    cells += f'<td class="center"><span class="pill {cls}">{sh}</span></td>'
                else:
                    cells += '<td class="center">—</td>'
            rows_html += f'<tr><td class="{name_cls}">{row["Staff Name"]}</td><td class="center">{badge}</td>{cells}</tr>'

        th_days = "".join(f'<th>{lbl}</th>' for lbl in day_labels)

        return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8"><style>
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ background:#fff; font-family:Arial,sans-serif; color:#1a1a1a; padding:32px; font-size:12px; }}
h1 {{ font-size:22px; font-weight:700; letter-spacing:0.05em; margin-bottom:6px; color:#111; text-transform:uppercase; }}
.meta {{ font-size:10px; color:#888; margin-bottom:24px; }}
table {{ width:100%; border-collapse:collapse; }}
th {{ font-size:9px; font-weight:600; text-transform:uppercase; letter-spacing:0.1em; color:#888; padding:8px 6px; border-bottom:2px solid #e5e5e5; text-align:center; }}
th:first-child {{ text-align:left; }}
td {{ padding:9px 6px; border-bottom:1px solid #f0f0f0; color:#222; }}
td.name {{ font-weight:500; font-size:12px; min-width:160px; }}
td.name.off {{ color:#bbb; }}
td.center {{ text-align:center; color:#bbb; font-size:11px; }}
tr:nth-child(odd) td {{ background:#fafafa; }}
tr:nth-child(even) td {{ background:#fff; }}
.pill {{ display:inline-block; padding:2px 8px; border-radius:4px; font-size:10px; font-weight:600; }}
.p14 {{ background:#dbeafe; color:#1d4ed8; }}
.p18 {{ background:#ede9fe; color:#6d28d9; }}
.p19 {{ background:#d1fae5; color:#065f46; }}
.badge {{ display:inline-block; width:20px; height:20px; border-radius:50%; font-size:9px; font-weight:700; background:#f0f0f0; color:#555; text-align:center; line-height:20px; }}
footer {{ margin-top:20px; font-size:9px; color:#ccc; text-align:right; }}
</style></head><body>
<h1>Planning Semaine</h1>
<div class="meta">STAFF SCHEDULER · AUTO-GÉNÉRÉ</div>
<table>
  <thead><tr><th>Nom</th><th></th>{th_days}</tr></thead>
  <tbody>{rows_html}</tbody>
</table>
<footer>STAFF SCHEDULER · AUTO-GÉNÉRÉ</footer>
</body></html>"""


    def save_reporting(self) -> None:
        report_file = os.path.join(self.base_path, "outputs", "Shortage_Report.txt")
        with open(report_file, "w", encoding="utf-8") as f:
            f.write("========================================\n")
            f.write("           BAR SHORTAGE REPORT\n")
            f.write("========================================\n\n")
            found = False
            for idx, day in enumerate(self.days):
                daily, mgr = [], []
                for t in self.time_labels:
                    if self.s_manager[idx][t].varValue and self.s_manager[idx][t].varValue > 0:
                        mgr.append(f"  ! {int(self.s_manager[idx][t].varValue)} Managers: Missing in day {day} at {self.time_labels[t]}\n")
                        found = True
                    for role in self.roles:
                        v = self.s_worker[idx][t][role].varValue
                        if v and v > 0:
                            daily.append(f"  ! {self.time_labels[t]} - {role}: Missing {int(v)}")
                            found = True
                if daily:
                    f.write(f">>> {day.upper()}\n")
                    f.write("\n".join(daily) + "\n\n")
                if mgr:
                    f.write("\n".join(mgr) + "\n\n")
                if self.s_till[idx].varValue and self.s_till[idx].varValue > 0:
                    f.write(f"  ! Tills: Missing {int(self.s_till[idx].varValue)}\n")
                    found = True
            if not found:
                f.write("All shifts successfully filled. No shortages detected.\n")
        print(f"✔ Shortage report saved to: {report_file}")
