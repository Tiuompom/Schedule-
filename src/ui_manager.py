import pandas as pd
import FreeSimpleGUI as sg
from db_manager import StaffManager

### UI Manager: Handles all popups and SG windows but don't modify the data ### 
### Can be change to any other UI framework without changing the rest of the codebase, just need to respect the return values of each method ###


class StaffUI:
    """Handles all popups and SG windows for collecting the datas"""

    def __init__(self, staff_manager: StaffManager):
        self.sm = staff_manager
        sg.theme("LightBlue")


    ### POPUP FOR NEW STAFF ###
    def popup_new_staff(self, name) -> dict:
        """Popup to collect info for a new staff member."""
        """Returns a dict with the new staff infos"""

        layout = [
            [sg.Text(f"New Staff Detected: {name}", font=('Helvetica',12,'bold'))],
            [sg.Text("Role:"), sg.Combo(self.sm.config['mapping']['registry']['roles'], default_value='Null', key='-ROLE-')],
            [sg.Text("Till Authorized:"), sg.Combo(self.sm.config['mapping']['dropbox_yes_no'], default_value='Null', key='-TILL-')],
            [sg.Text("Is Manager:"), sg.Combo(self.sm.config['mapping']['dropbox_yes_no'], default_value='Null', key='-MGR-')],
            [sg.Button("Save")]
        ]
        
        window = sg.Window(f"Registry Update: {name}", layout, disable_close=True, keep_on_top=True)

        while True:
            event, values = window.read()
            if event == "Save":
                if any(values[k]=='Null' for k in ['-ROLE-', '-TILL-', '-MGR-']):
                    sg.popup_error("All fields must be selected!", keep_on_top=True)
                    continue
                data = {'Role': values['-ROLE-'], 'Till_Authorized': values['-TILL-'], 'Is_Manager': values['-MGR-'], 'Email': self.sm.staff_availability[self.sm.staff_availability['Name']==name]['Adresse e-mail'].values[0]}
                window.close()
                return data 

    ### CONFIRM GHOST WORKER ###

    def confirm_ghost_worker(self, name) -> bool:
        """Popup to confirm deletion of ghost worker."""
        return sg.popup_yes_no(f"{name} missing from availibility. Delete from registry?", no_titlebar=True, keep_on_top=True) == "Yes"

    ### MODIFY STAFF REGISTER ###

    def modify_staff_register(self, name_list) -> list[dict]:
        """Popup to select a worker and modify their attributes."""
        updates = []
        while True:
            choice = sg.popup_yes_no("Do you want to modify a worker's attributes?", no_titlebar=True, keep_on_top=True)
            if choice != "Yes":
                return updates

            layout = [
                [sg.Text("Select a worker to modify:", font=('Helvetica',12))],
                [sg.Combo(name_list, key='-NAME-', readonly=True, size=(30,1))],
                [sg.Button("Edit"), sg.Button("Cancel")]
            ]
            window = sg.Window("Select Staff", layout, disable_close=True, finalize=True, keep_on_top=True)
            event, values = window.read()
            window.close()

            if event == "Edit" and values['-NAME-']:
                name = values['-NAME-']
                data = self.popup_new_staff(name)
                if data:
                    updates.append({
                        "Name": name,
                        "data": data
                    })


    ### MODIFY DEMAND ###
    def modify_demand(self) -> pd.DataFrame :
        """Simplified Demand Editor: Select Day -> Select Time -> Modify Roles."""
        demand = self.sm.need_for_staff.copy()
        roles = demand["Role"].tolist()
        demand.set_index("Role", inplace=True)
        days = self.sm.config['structure']['days']
        times = list(self.sm.config['structure']['time_labels'].values())
        
        if sg.popup_yes_no("Modify the staff demand for this week?", keep_on_top=True) != "Yes":
            return None

        while True:
            # 1. Selection Layout
            select_layout = [
                [sg.Text("Select Day:", size=(10, 1)), sg.Combo(days, key='-DAY-', readonly=True)],
                [sg.Text("Select Time:", size=(10, 1)), sg.Combo(times, key='-TIME-', readonly=True)],
                [sg.Button("Edit Slot")],
                [sg.Button("Save & Exit")]
            ]
            
            sel_window = sg.Window("Select Shift", select_layout, keep_on_top=True)
            event, values = sel_window.read()
            sel_window.close()

            if event in ("Save & Exit"):
                break # return the demand df 

            if event == "Edit Slot" and values['-DAY-'] and values['-TIME-']:
                col_name = f"{values['-DAY-'][:3]} {values['-TIME-']}"
                
                # Store original values for this specific slot to calculate the diff
                original_slot_values = {role: int(demand.at[role, col_name]) for role in roles}
                
                edit_layout = [[sg.Text(f"Adjusting: {col_name}", font=('Helvetica', 12, 'bold'))]]
                
                for role in roles:
                    val = original_slot_values[role]
                    edit_layout.append([
                        sg.Text(f"{role}:", size=(12, 1)),
                        sg.Spin(values=list(range(0, 10)), initial_value=val, 
                                key=role, size=(5, 1), enable_events=True),
                        sg.Text("", size=(5, 1), key=f"-DIFF-{role}-")
                    ])
                
                edit_layout.append([sg.Button("Apply"), sg.Button("Cancel")])
                
                edit_window = sg.Window(f"Edit {col_name}", edit_layout, keep_on_top=True)
                
                # Nested Event Loop for the Edit Window
                while True:
                    e_event, e_values = edit_window.read()
                    
                    if e_event in (None, "Cancel"):
                        break
                    
                    ### Indicator Logic: Compare current value with original and show diff in green/red
                    if e_event in roles:
                        current = int(e_values[e_event])
                        original = original_slot_values[e_event]
                        diff = current - original
                        
                        indicator_key = f"-DIFF-{e_event}-"
                        if diff > 0:
                            edit_window[indicator_key].update(f"+{diff}", text_color="green")
                        elif diff < 0:
                            edit_window[indicator_key].update(f"{diff}", text_color="red")
                        else:
                            edit_window[indicator_key].update("", text_color="black")

                    if e_event == "Apply":
                        for role in roles:
                            demand.at[role, col_name] = int(e_values[role])
                        break
                
                edit_window.close()

        return demand
    
    def show_error_message(self) -> None:
        sg.popup_error("An error occurred. Send the log file to the administrator for troubleshooting", keep_on_top=True)
    
    def show_info_message(self, message) -> None:
        sg.popup(message, keep_on_top=True)
    
    def validate_smtg(self, message) -> bool:
        return sg.popup_yes_no(message, keep_on_top=True) == "Yes"