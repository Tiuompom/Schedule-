import pulp
import pandas as pd 
from db_manager import StaffManager

class OptimizerManager:
    def __init__(self, staff_manager: StaffManager):
        self.staff_manager = staff_manager
        ### parameters for the optimization problem
        self.availability, self.need, self.counting, self.manager, self.possible_role = self.create_parameters()
        self.sol, self.s_work, self.s_till, self.s_mana = self.solve()

    def solve(self) -> tuple:
        """ Solve the scheduling optimization problem using PuLP and return the proposed solution and slacks for the shortage in staff, till and manager """
        ### Instantiate the problem 

        prob = pulp.LpProblem("Scheduling_Optimization", pulp.LpMinimize)

        ### Create Indices 
        workers = self.staff_manager.staff_availability["Name"].tolist()

        day_names = self.staff_manager.config['structure']['days'] # Number of working day in a week 
        days = list(range(len(day_names)))
        times = range(self.staff_manager.config['structure']['shifts']) # Number of starting time in a day
        night = self.staff_manager.config['structure']['night_shifts'] # Night shifts indices for flag the 
        roles = self.staff_manager.config['structure']['roles'] # Available role

        ### Create Decision Variables
        x      = pulp.LpVariable.dicts("x",      (workers, days, times, roles), cat=pulp.LpBinary)
        s_work = pulp.LpVariable.dicts("s_work",  (days, times, roles), lowBound=0, cat=pulp.LpInteger)
        s_till = pulp.LpVariable.dicts("s_till",  (days),               lowBound=0, cat=pulp.LpInteger)
        s_mana = pulp.LpVariable.dicts("s_mana",  (days, times),        lowBound=0, cat=pulp.LpInteger)

        # Equité : w_max = shifts du worker le plus chargé, w_min = le moins chargé
        # On minimise w_max - w_min pour répartir équitablement la charge
        w_max = pulp.LpVariable("w_max", lowBound=0, cat=pulp.LpInteger)
        w_min = pulp.LpVariable("w_min", lowBound=0, cat=pulp.LpInteger)

        ### Objectif : priorité absolue aux pénuries, équité en secondaire
        # Le coefficient 1000 garantit que combler une pénurie prime toujours sur l'équité
        shortage_penalty = (
            pulp.lpSum(s_work[j][t][role] for j in days for t in times for role in roles)
            + pulp.lpSum(s_till[j] for j in days)
            + pulp.lpSum(s_mana[j][t] for j in days for t in times)
        )
        prob += 1000 * shortage_penalty + (w_max - w_min)

        ### Constraints 

        ## 1. Availability + role eligibility constraints
        for i in workers:
            for j in days:
                for t in times:
                    for role in roles:
                        # Block assignment if worker is not available
                        prob += x[i][j][t][role] <= self.availability[i][j][t]
                        # Block assignment if worker's role doesn't match
                        if self.possible_role[i] != role and self.possible_role[i] != 'Both':
                            prob += x[i][j][t][role] == 0

        ## 2. Demand Satisfcation 
        for j in days:
            for t in times:
                for role in roles:
                    prob += (
                        pulp.lpSum(
                            x[i][j][t][role]
                            for i in workers
                            if self.possible_role[i] == role or self.possible_role[i] == 'Both'
                        )
                        + s_work[j][t][role]
                        == self.need[j][t][role]
                    )


        ## 3. Only one possible starting time for each worker for each day 
        for i in workers : 
            for j in days :
                prob += pulp.lpSum([x[i][j][t][role] for t in times for role in roles]) <= 1

        ## 4. One night worker needs to do the till 
        for j in days:
            ### ONLY require a till worker if at least one night shift has demand
            if any(self.need[j][t][role] > 0 for t in night for role in roles):
                prob += pulp.lpSum([x[i][j][t][role] * self.counting[i] for i in workers for role in roles for t in night]) + s_till[j] >= 1 

        ## 5. At least one manager is present 
        for j in days:
            for t in night:
            ### ONLY require a manager if the bar is actually open  (Can be modified by detecting the closed days)
                if sum(self.need[j][t][role] for role in roles) > 0: # Night
                    prob += pulp.lpSum([x[i][j][t][role] * self.manager[i] for i in workers for role in roles]) + s_mana[j][t] >= 1

                    
        ## 6. Equité : borner w_max et w_min par le nombre de shifts de chaque worker
        for i in workers:
            shifts_i = pulp.lpSum(x[i][j][t][role] for j in days for t in times for role in roles)
            prob += w_max >= shifts_i   # w_max est au moins égal aux shifts de i
            prob += w_min <= shifts_i   # w_min est au plus égal aux shifts de i

        prob.solve(pulp.PULP_CBC_CMD(msg=0))
        
        return x, s_work, s_till, s_mana
    
    
    def transform_df(self) -> pd.DataFrame: 
        """ Transform the staff availability relative to days into a binary datgaframe relative to each possible shifts"""
        ### Based only on google form csv output format 

        ### Last Entry filtering
        availability = self.staff_manager.staff_availability.copy()
        availability['Horodateur'] = pd.to_datetime(availability['Horodateur'])
        availability = availability.sort_values('Horodateur').drop_duplicates('Adresse e-mail', keep='last')

        ### Define the target structure
        days = self.staff_manager.config['structure']['days']
        hours = self.staff_manager.config['structure']['time_labels'].values()
        
        ### Initialize result with Names
        result_data = {"Name": availability['Name']}
        
        ### Transform csv format into a binary indicator of availability for each time slot
        for day in days:
            for hour in hours:
                ### Create the header name like "Mon 14h" Matching the need_for_staff format
                col_name = f"{day[:3]} {hour}"
                
                # Search for the hour in the day string (ignoring spaces)
                result_data[col_name] = availability[day].fillna("").apply(
                    lambda x: 1 if hour in str(x).replace(" ", "") else 0
                )
                
        df = pd.DataFrame(result_data)
        return df

    @staticmethod
    def _to_binary(val) -> int:
        """Convert Yes/No/True/False/1/0 to 1 or 0."""
        return 1 if str(val).strip().lower() in ('yes', 'true', '1') else 0

    def apply_mapping(self) -> pd.DataFrame:
        """Convert Till_Authorized and Is_Manager to binary regardless of source format."""
        df = self.staff_manager.staff_register.copy()
        df['Till_Authorized'] = df['Till_Authorized'].apply(self._to_binary)
        df['Is_Manager']      = df['Is_Manager'].apply(self._to_binary)
        return df

    def create_parameters(self) -> tuple: 
        """ Create the parameters for the optimization problem based on the staff register, availability and need for staff after applying the necessary transformations and mapping"""
        availability = self.transform_df().set_index("Name")
        register = self.apply_mapping().set_index("Name")
        demand = self.staff_manager.need_for_staff.set_index("Role")

        day_names = self.staff_manager.config['structure']['days'] # Number of working day in a week 
        days = list(range(len(day_names)))
        times = range(self.staff_manager.config['structure']['shifts']) # Number of starting time in a day

        ### Create parameter d[i][j][t]
        d = {}
        workers = availability.index.tolist()
        cols = availability.columns
        
        for worker in workers:
            d[worker] = {}
            for j in range(len(days)): 
                d[worker][j] = {}
                for t in times: 
                    col_idx = j * 3 + t
                    if col_idx < len(cols):
                        val = availability.loc[worker, cols[col_idx]]
                        d[worker][j][t] = 1.0 if val > 0.0 else 0.0
                    else:
                        d[worker][j][t] = 0.0 ### safety

        ### Create parameter n[j][t][r]
        role = demand.index.tolist()
        n = {}
        for j in range(len(days)):
            n[j] = {}
            for t in times: 
                n[j][t] = {}
                col_idx = j * 3 + t
                for position in role : 
                    if col_idx < len(cols):
                        n[j][t][position] = int(demand.loc[position, demand.columns[col_idx]])
                    else : 
                        n[j][t][position] = 0.0
        
        ### Create parameter c[i]
        if 'Name' in register.columns:
            register = register.set_index('Name')
        c = {}
        for worker in workers : 
            c[worker] = register.loc[worker,'Till_Authorized']
        
        ### Create parameter m[i]
        m = {}
        for worker in workers : 
            m[worker] = register.loc[worker, 'Is_Manager']
        
        ### Create parameter r[i]
        r = {}
        for worker in workers : 
            r[worker] = register.loc[worker, 'Role']

        return d, n, c, m, r
