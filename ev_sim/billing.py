
class Billing_Engine:
    PEAK_RATE = 0.55
    OFF_PEAK_RATE = 0.30
    OFF_PEAK_END_HOUR = 6
    OFF_PEAK_START_HOUR = 22
    VIP_DISCOUNT = 0.8
    IDLE_FEE_RATE = 0.5 # dollars per minute after grace period
    GRACE_PERIOD_SECONDS = 900 # 15 minutes
    FAST_CHARGE_MULTIPLIER = 1.5
    @classmethod
    def get_electricity_rate(cls,time_stamp):
        seconds_in_day = time_stamp % 86400
        hours_in_day = seconds_in_day /3600
        if hours_in_day <6 or hours_in_day >=22:
            return cls.OFF_PEAK_RATE
        else:
            return cls.PEAK_RATE
    @classmethod
    def next_rate_boundary(cls, t):
        day_start = t - (t%86400)
        hour = (t - day_start)/3600
        if hour < cls.OFF_PEAK_END_HOUR:
            return day_start + cls.OFF_PEAK_END_HOUR * 3600
        elif hour < cls.OFF_PEAK_START_HOUR:
            return day_start + cls.OFF_PEAK_START_HOUR * 3600
        return day_start + 86400 + cls.OFF_PEAK_END_HOUR * 3600


    @classmethod
    def calculate_interval_cost(cls, start, end, power_kw):
        """Cost of charging at power_kw from start to end, split at peak/off-peak boundaries."""
        cost = 0.0
        t = start
        while t <end:
            seg_end= min(end, cls.next_rate_boundary(t))
            cost += power_kw * (((seg_end - t)/3600) * cls.get_electricity_rate(t))
            t = seg_end
        return cost
    @classmethod
    def calculate_charging_cost(cls, start,end,power_kw,port_type):
        cost = cls.calculate_interval_cost(start,end,power_kw)
        if port_type == "FAST":
            cost *= cls.FAST_CHARGE_MULTIPLIER
        return cost
            


    @classmethod
    def calculate_idlefee(cls,vehicle,unplug_timestamp):
        idle_time = unplug_timestamp- vehicle.completed_timestamp if vehicle.completed_timestamp is not None else 0.0
        idle_fee = (idle_time-cls.GRACE_PERIOD_SECONDS) *(cls.IDLE_FEE_RATE/60)  if idle_time >cls.GRACE_PERIOD_SECONDS else 0.0
        return idle_fee

    @classmethod
    def calculate_discounted_energy_bill(cls,vehicle):
        raw_energy_cost = vehicle.total_energy_cost * cls.VIP_DISCOUNT if vehicle.user_tier == "VIP" else vehicle.total_energy_cost
        return raw_energy_cost
