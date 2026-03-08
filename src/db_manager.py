import pandas as pd
import os

_AVAIL_COLS = ['Horodateur', 'Name', 'Adresse e-mail',
               'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

class StaffManager:
    """Loads and manages the three CSV data sources."""

    def __init__(self, paths, config):
        self.config   = config
        data_path     = paths['data']

        self.staff_register = self._load_required(data_path, config, 'staff_register')
        self.need_for_staff = self._load_required(data_path, config, 'need_for_staff')

        avail_path = os.path.join(data_path, config["names_df"]["staff_availability"])
        try:
            self.staff_availability = pd.read_csv(avail_path)
        except FileNotFoundError:
            self.staff_availability = pd.DataFrame(columns=_AVAIL_COLS)

    def _load_required(self, data_path, config, key) -> pd.DataFrame:
        df       = pd.read_csv(os.path.join(data_path, config["names_df"][key]))
        expected = set(config["headers"][key])
        missing  = expected - set(df.columns)
        extra    = set(df.columns) - expected
        if missing: raise ValueError(f"{key}.csv missing columns: {missing}")
        if extra:   raise ValueError(f"{key}.csv unexpected columns: {extra}")
        return df

    def validate_availability(self) -> None:
        """Call after an upload to verify headers."""
        expected = set(self.config["headers"]["staff_availability"])
        missing  = expected - set(self.staff_availability.columns)
        extra    = set(self.staff_availability.columns) - expected
        if missing: raise ValueError(f"staff_availability.csv missing columns: {missing}")
        if extra:   raise ValueError(f"staff_availability.csv unexpected columns: {extra}")

    # ── CRUD ────────────────────────────────────────────────────────────────
    def add_staff(self, name, info) -> None:
        self.staff_register = pd.concat(
            [self.staff_register, pd.DataFrame([{'Name': name, **info}])], ignore_index=True)

    def remove_staff(self, name) -> None:
        self.staff_register = self.staff_register[self.staff_register['Name'] != name]

    def update_staff(self, name, info) -> None:
        mask = self.staff_register['Name'] == name
        for col in ('Role', 'Till_Authorized', 'Is_Manager'):
            self.staff_register.loc[mask, col] = info[col]
