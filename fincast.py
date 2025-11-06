#!/usr/bin/env python

import csv
import datetime
import sys
from dataclasses import dataclass, field
from enum import Enum

import yaml


def generate_date_range(start_date: datetime.date, end_date: datetime.date):
    for n in range(int((end_date - start_date).days)):
        yield start_date + datetime.timedelta(n)


def generate_biweekly_dates(
    start_date: datetime.date, end_date: datetime.date
) -> list[datetime.date]:
    dates: list[datetime.date] = []
    for n in range(0, int((end_date - start_date).days), 14):
        dates.append(start_date + datetime.timedelta(n))
    return dates


def date(year: int, month: int, day: int) -> datetime.date:
    return datetime.date(year, month, day)


@dataclass
class Interval:
    start_date: datetime.date | None = None
    end_date: datetime.date | None = None


@dataclass
class OnetimeInterval(Interval):
    date: datetime.date = date(2000, 1, 1)
    # can be used for a one time payment targeting a specific
    # BudgetItem (by name)
    # if None, then no target BudgetItem is referenced
    target: str | None = None


@dataclass
class MonthlyInterval(Interval):
    day: int = 1


@dataclass
class DailyInterval(Interval):
    pass


@dataclass
class WeeklyInterval(Interval):
    day_of_week: int = 0


@dataclass
class BiWeeklyInterval(Interval):
    """use generate_biweekly_dates() to generate this list"""

    dates: list[datetime.date] = field(default_factory=list)


@dataclass
class YearlyInterval(Interval):
    month: int = 1
    day: int = 1


class BudgetItemType(Enum):
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"


@dataclass
class BudgetItem:
    name: str
    interval: (
        YearlyInterval
        | MonthlyInterval
        | BiWeeklyInterval
        | WeeklyInterval
        | DailyInterval
        | OnetimeInterval
    )
    type: BudgetItemType = BudgetItemType.EXPENSE
    amount: float = float(0.0)
    total_paid: float = float(0.0)
    interest: float = float(0.0)
    interest_paid: float = float(0.0)
    # NOTE: remaining_balance of None indicates this item is recurring
    remaining_balance: float | None = None
    # when this item is paid off, move this amount to another item
    move_payment_to: str | None = None
    done: bool = False


class BudgetCalculator:
    def __init__(
        self,
        *,
        account_balance: float,
        start_date: datetime.date,
        end_date: datetime.date,
        config: dict[str, BudgetItem],
        csv_output_file: str,
    ):
        self.account_balance = account_balance
        self.start_date = start_date
        self.end_date = end_date
        self.config = config
        self.csv_output_file = csv_output_file
        self.cur_day: datetime.date = start_date
        self.csv_fd = open(self.csv_output_file, "w")
        self.csv_writer = csv.DictWriter(
            self.csv_fd,
            [
                "date",
                "name",
                "amount",
                "remaining",
                "total_paid",
                "total_interest",
                "account_balance",
                "interval",
                "type",
                "note",
            ],
        )
        self.csv_writer.writeheader()
        self.csv_row: dict = {}

    def calculate_generic(self, item: BudgetItem):
        final_balance = False
        if item.remaining_balance is not None:
            amount = min(item.amount, item.remaining_balance)
            if amount < item.amount:
                final_balance = True
        else:
            amount = item.amount
        self.csv_row = {
            "date": "",
            "name": "",
            "amount": "",
            "remaining": "",
            "total_paid": "",
            "total_interest": "",
            "account_balance": "",
            "interval": "",
            "type": "",
            "note": "",
        }
        if amount > 0:
            interest = float(0.0)
            if item.interest > 0:
                # subtract interest
                interest = amount * item.interest
            if item.type == BudgetItemType.EXPENSE:
                self.account_balance -= amount
                item.total_paid += amount
                if item.remaining_balance is not None:
                    item.remaining_balance -= amount - interest
                    if final_balance:
                        item.remaining_balance = float(0.0)
                item.interest_paid += interest
            elif item.type == BudgetItemType.INCOME:
                self.account_balance += amount
                item.total_paid += amount
            self.csv_row = {
                "date": "",
                "name": item.name.replace("_", " ").title(),
                "amount": amount,
                "remaining": item.remaining_balance,
                "total_paid": item.total_paid,
                "total_interest": item.interest_paid,
                "account_balance": self.account_balance,
                "interval": item.interval.__class__.__name__,
                "type": item.type.value,
                "note": "",
            }

    def calculate_onetime(self, item: BudgetItem):
        """expects interval to be OnetimeInterval"""
        assert isinstance(item.interval, OnetimeInterval)
        # check if this targeted a specific BudgetItem
        if item.interval.target:
            target = self.config.get(item.interval.target, None)
            assert target, (
                f"invalid config: missing BudgetItem target: {item.interval.target}"
            )
            if target.type == BudgetItemType.EXPENSE:
                self.account_balance -= item.amount
                target.total_paid += item.amount
                if target.remaining_balance:
                    target.remaining_balance -= item.amount
            elif target.type == BudgetItemType.INCOME:
                self.account_balance += item.amount
                target.total_paid += item.amount

            if target.remaining_balance and target.remaining_balance <= 0:
                target.done = True
            self.csv_row = {
                "date": "",
                "name": target.name.replace("_", " ").title(),
                "amount": target.amount,
                "remaining": target.remaining_balance,
                "total_paid": target.total_paid,
                "total_interest": target.interest_paid,
                "account_balance": self.account_balance,
                "interval": target.interval.__class__.__name__,
                "type": target.type.value,
                "note": f"onetime payment: {item.name}",
            }
        else:
            if item.type == BudgetItemType.EXPENSE:
                self.account_balance -= item.amount
                item.total_paid += item.amount
                item.remaining_balance = float(0.0)
            elif item.type == BudgetItemType.INCOME:
                self.account_balance += item.amount
                item.total_paid += item.amount

            self.csv_row = {
                "date": "",
                "name": item.name.replace("_", " ").title(),
                "amount": item.amount,
                "remaining": item.remaining_balance,
                "total_paid": item.total_paid,
                "total_interest": item.interest_paid,
                "account_balance": self.account_balance,
                "interval": item.interval.__class__.__name__,
                "type": item.type.value,
                "note": "onetime payment",
            }

    def calculate_daily(self, item: BudgetItem):
        """expects interval to be DailyInterval"""
        assert isinstance(item.interval, DailyInterval)
        self.calculate_generic(item)

    def calculate_weekly(self, item: BudgetItem):
        """expects interval to be WeeklyInterval"""
        assert isinstance(item.interval, WeeklyInterval)
        self.calculate_generic(item)

    def calculate_biweekly(self, item: BudgetItem):
        """expects interval to be BiWeeklyInterval"""
        assert isinstance(item.interval, BiWeeklyInterval)
        self.calculate_generic(item)

    def calculate_monthly(self, item: BudgetItem):
        """expects interval to be MonthlyInterval"""
        assert isinstance(item.interval, MonthlyInterval)
        self.calculate_generic(item)

    def calculate_yearly(self, item: BudgetItem):
        """expects interval to be YearlyInterval"""
        assert isinstance(item.interval, YearlyInterval)
        self.calculate_generic(item)

    def date_in_range(self, item: BudgetItem, cur_date: datetime.date) -> bool:
        """check if cur_date is within item.interval date start/end"""

        if item.interval.start_date:
            if cur_date < item.interval.start_date:
                return False
        if item.interval.end_date:
            if cur_date > item.interval.end_date:
                return False
        return True

    def maybe_write_csv_row(self, date_str: str):
        fix_fields = (
            "amount",
            "remaining",
            "total_paid",
            "total_interest",
            "account_balance",
        )
        if self.csv_row.get("name", ""):
            self.csv_row["date"] = date_str
            # convert decimal to 2 decimal places,
            # otherwise it shows up as scientific notation
            for key in fix_fields:
                if self.csv_row[key]:
                    self.csv_row[key] = f"{self.csv_row[key]:.2f}"
                else:
                    self.csv_row[key] = ""
            self.csv_writer.writerow(self.csv_row)

    def run(self):
        for cur_date in generate_date_range(self.start_date, self.end_date):
            date_str = cur_date.strftime("%Y-%m-%d")
            for _, item in self.config.items():
                self.csv_row: dict = {}
                if item.done:
                    continue
                if item.interval.end_date and cur_date > item.interval.end_date:
                    item.done = True
                    continue
                if not self.date_in_range(item, cur_date):
                    continue
                if isinstance(item.interval, OnetimeInterval):
                    self.calculate_onetime(item)
                    item.done = True
                elif isinstance(item.interval, DailyInterval):
                    self.calculate_daily(item)
                elif isinstance(item.interval, WeeklyInterval):
                    if cur_date.weekday() == item.interval.day_of_week:
                        self.calculate_weekly(item)
                elif isinstance(item.interval, BiWeeklyInterval):
                    if cur_date in item.interval.dates:
                        self.calculate_biweekly(item)
                elif isinstance(item.interval, MonthlyInterval):
                    if cur_date.day == item.interval.day:
                        self.calculate_monthly(item)
                elif isinstance(item.interval, YearlyInterval):
                    if (
                        cur_date.day == item.interval.day
                        and cur_date.month == item.interval.month
                    ):
                        self.calculate_yearly(item)
                else:
                    raise AttributeError(
                        f"invalid interval type: {type(item.interval)}"
                    )
                self.check_if_done(item)
                self.maybe_write_csv_row(date_str)

        self.csv_fd.flush()
        self.csv_fd.close()

    def check_if_done(self, item: BudgetItem):
        if item.done:
            return
        if item.remaining_balance is not None and item.remaining_balance <= 0:
            item.done = True
            if self.csv_row["note"]:
                self.csv_row["note"] += " balance closed."
            else:
                self.csv_row["note"] = " balance closed."
        if item.type == BudgetItemType.EXPENSE:
            if (
                item.remaining_balance is not None
                and item.remaining_balance <= 0
                and item.move_payment_to
            ):
                # move paid off item amount to destination
                dst_item = self.config.get(item.move_payment_to, None)
                assert dst_item, (
                    f"invalid config: move_payment_to does not exist: {item.move_payment_to}"
                )
                if (
                    dst_item.remaining_balance is not None
                    and dst_item.remaining_balance > 0
                ):
                    print(
                        f"move_payment_to: {item.name} -> {item.move_payment_to} {dst_item.remaining_balance=}"
                    )
                    dst_item.amount += item.amount
                    self.csv_row["note"] = (
                        f"balance closed. move_payment_to: {item.move_payment_to}"
                    )


def create_budget_object(
    name: str,
    v: dict,
    global_start_date: datetime.date,
    global_end_date: datetime.date,
    budge_item_type: BudgetItemType,
) -> BudgetItem | None:
    amount = v.get("amount", 0.0)
    interval = v.get("interval", "")
    remaining_balance = v.get("remaining_balance", None)
    if remaining_balance is not None:
        remaining_balance = float(remaining_balance)
    move_payment_to = str(v.get("move_payment_to", ""))
    interest = float(v.get("interest", 0.0))
    interest_paid = float(v.get("interest_paid", 0.0))
    total_paid = v.get("total_paid", 0.0)
    start_date = v.get("start_date", None)
    end_date = v.get("end_date", None)
    day = int(v.get("day", 0))
    day_of_week = int(v.get("day_of_week", 0))
    month = int(v.get("month", "0"))
    year = int(v.get("year", "0"))
    target = str(v.get("target", ""))

    try:
        if start_date:
            start_year, start_month, start_day = start_date.split("-")
            start_date = date(int(start_year), int(start_month), int(start_day))
        else:
            start_date = global_start_date
    except Exception as e:
        print(f"E: failed to parse start_date (YYYY-mm-dd): {start_date} -> {e}")
        return None
    try:
        if end_date:
            end_year, end_month, end_day = end_date.split("-")
            end_date = date(int(end_year), int(end_month), int(end_day))
        else:
            end_date = global_end_date
    except Exception as e:
        print(f"E: failed to parse end_date (YYYY-mm-dd): {end_date} -> {e}")
        return None
    if not interval:
        print(f"E: interval is required for item: {name}")
        return None

    interval_obj: (
        YearlyInterval
        | MonthlyInterval
        | BiWeeklyInterval
        | WeeklyInterval
        | DailyInterval
        | OnetimeInterval
    ) = OnetimeInterval(start_date=start_date, end_date=end_date, target=target)
    if interval == "yearly":
        interval_obj = YearlyInterval(
            month=month, day=day, start_date=start_date, end_date=end_date
        )
    elif interval == "monthly":
        interval_obj = MonthlyInterval(
            day=day, start_date=start_date, end_date=end_date
        )
    elif interval == "biweekly":
        interval_obj = BiWeeklyInterval(
            start_date=start_date,
            end_date=end_date,
            dates=generate_biweekly_dates(start_date, end_date),
        )
    elif interval == "weekly":
        interval_obj = WeeklyInterval(
            day_of_week=day_of_week, start_date=start_date, end_date=end_date
        )
    elif interval == "daily":
        interval_obj = DailyInterval(start_date=start_date, end_date=end_date)
    elif interval == "once":
        date_obj = date(year, month, day)
        interval_obj = OnetimeInterval(
            start_date=date_obj, end_date=date_obj, date=date_obj, target=target
        )
    else:
        print(f"E: invalid interval: {interval}")
        return None
    return BudgetItem(
        name=name,
        interval=interval_obj,
        type=budge_item_type,
        amount=amount,
        total_paid=total_paid,
        interest=interest,
        interest_paid=interest_paid,
        remaining_balance=remaining_balance,
        move_payment_to=move_payment_to,
    )


def dump():
    path = sys.argv[1]
    with open(path) as fd:
        data = yaml.safe_load(fd)
    expenses = data.get("expenses", {})
    income = data.get("income", {})
    global_config = data.get("global", {})
    outfile = global_config.get("outfile", "budget_output.csv")
    global_balance = global_config.get("balance", 100.00)
    global_start_date = global_config.get("start_date", None)
    global_end_date = global_config.get("end_date", None)
    if not global_end_date:
        global_end_date = datetime.datetime.date(datetime.datetime.now())
    if not expenses:
        print("E: yaml file does not have an 'expenses' section with items defined.")
        return
    config_objects = {}
    for name, v in income.items():
        item = create_budget_object(
            name, v, global_start_date, global_end_date, BudgetItemType.INCOME
        )
        if item:
            config_objects[name] = item
    for name, v in expenses.items():
        item = create_budget_object(
            name, v, global_start_date, global_end_date, BudgetItemType.EXPENSE
        )
        if item:
            config_objects[name] = item

    calculator = BudgetCalculator(
        account_balance=global_balance,
        start_date=global_start_date,
        end_date=global_end_date,
        config=config_objects,
        csv_output_file=outfile,
    )
    calculator.run()
    print(f"wrote: {outfile}")


if __name__ == "__main__":
    dump()
