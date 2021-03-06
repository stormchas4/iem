"""Plot 1 minute ASOS data."""
from datetime import timezone, timedelta
from collections import OrderedDict

import pytz
import pandas as pd
import numpy as np
from pandas.io.sql import read_sql
from matplotlib.dates import DateFormatter
from metpy.units import units, masked_array
from pyiem.util import get_autoplot_context, get_dbconn, utc
from pyiem.plot.use_agg import plt
from pyiem.exceptions import NoDataFound

PDICT = OrderedDict(
    [
        ("precip", "Precipitation Plot"),
        ("wind", "Wind Speed + Direction Plot [MPH]"),
        ("windkt", "Wind Speed + Direction Plot [KNOTS]"),
    ]
)


def get_description():
    """ Return a dict describing how to call this plotter """
    desc = dict()
    desc["data"] = True
    desc[
        "description"
    ] = """This application generates charts of 1 minute interval ASOS data,
    where available.  It presently lists all ASOS sites without limiting them
    to which the IEM has data for, sorry.  You can only select up to 5 days
    worth of data at this time.  Any reported 1 minute precipitation value
    over 0.50 inches is omitted as bad data."""
    sts = utc() - timedelta(days=2)
    desc["arguments"] = [
        dict(
            type="select",
            name="ptype",
            options=PDICT,
            default="precip",
            label="Available Plot Type:",
        ),
        dict(
            type="zstation",
            name="zstation",
            default="AMW",
            network="IA_ASOS",
            label="Select Station:",
        ),
        dict(
            type="datetime",
            name="sts",
            default=sts.strftime("%Y/%m/%d 0000"),
            label="Search archive starting at (UTC Timestamp) (inclusive):",
            min="2000/01/01 0000",
        ),
        dict(
            type="datetime",
            name="ets",
            default=sts.strftime("%Y/%m/%d 2359"),
            label="Search archive ending at (UTC Timestamp) (exclusive):",
            min="2000/01/01 0000",
        ),
    ]
    return desc


def get_data(ctx):
    """Fetch Data."""
    pgconn = get_dbconn("asos1min")
    df = read_sql(
        "SELECT valid at time zone 'UTC' as valid, "
        "case when precip > 0.49 then null else precip end as precip, "
        "sknt, drct, gust_sknt from "
        "alldata_1minute WHERE station = %s and valid >= %s and valid < %s "
        "ORDER by valid ASC",
        pgconn,
        params=(ctx["zstation"], ctx["sts"], ctx["ets"]),
        index_col="valid",
    )
    if df.empty:
        raise NoDataFound("No database entries found for station and dates.")
    # assign the UTC timezone to the index
    df.index = df.index.tz_localize(timezone.utc)
    # Complete the dataframe for the time period of interest
    df = df.reindex(
        pd.date_range(ctx["sts"], ctx["ets"] - timedelta(minutes=1), freq="1T")
    )
    df.index.name = "utc_valid"
    df = df.reset_index()
    # Create a local valid time column
    ctx["tz"] = pytz.timezone(ctx["_nt"].sts[ctx["zstation"]]["tzname"])
    df["local_valid"] = df["utc_valid"].dt.tz_convert(ctx["tz"])
    return df


def do_xaxis(ctx, ax):
    """Make a sensible xaxis."""
    timerange = ctx["ets"] - ctx["sts"]
    if timerange > timedelta(days=1):
        fmt = "%-m/%-d\n%-I %p"
    else:
        fmt = "%-I:%M %p"
    ax.xaxis.set_major_formatter(DateFormatter(fmt, tz=ctx["tz"]))
    ax.set_xlabel(f"Plot Timezone: {ctx['tz']}")


def make_wind_plot(ctx, ptype):
    """Generate a wind plot, please."""
    df = ctx["df"]
    (fig, ax) = plt.subplots(1, 1)
    gust = df["gust_sknt"].values
    sknt = df["sknt"].values
    unit = "kt"
    if ptype == "wind":
        gust = masked_array(gust, units("knots")).to(units("miles per hour")).m
        sknt = masked_array(sknt, units("knots")).to(units("miles per hour")).m
        unit = "mph"
    ax.bar(
        df["local_valid"].values,
        gust,
        zorder=1,
        width=1.0 / 1440.0,
        label="Gust",
    )
    ax.bar(
        df["local_valid"].values,
        sknt,
        zorder=2,
        width=1.0 / 1440.0,
        label="Speed",
    )
    ax.set_ylabel(f"Wind Speed / Gust [{unit}]")
    ax.grid(True)
    ax.legend(loc="best")
    ax2 = ax.twinx()
    ax2.scatter(df["local_valid"].values, df["drct"].values, c="k")
    ax2.set_ylabel("Wind Direction")
    ax2.set_yticks(np.arange(0, 361, 45))
    ax2.set_yticklabels(["N", "NE", "E", "SE", "S", "SW", "W", "NW", "N"])
    ax2.set_ylim(-1, 361)
    ax.set_title(
        (
            f"{get_ttitle(df)} %s (%s)\n"
            "One Minute Interval Wind Speed + Direction, %s missing minutes\n"
            f"Peak Speed: %.1f {unit} Peak Gust: %.1f {unit}"
        )
        % (
            ctx["_nt"].sts[ctx["zstation"]]["name"],
            ctx["zstation"],
            df["sknt"].isna().sum(),
            np.nanmax(sknt),
            np.nanmax(gust),
        )
    )
    do_xaxis(ctx, ax)
    ax.set_xlim(df["local_valid"].min(), df["local_valid"].max())
    return fig


def get_ttitle(df):
    """Helper."""
    lvmin, lvmax = df["local_valid"].min(), df["local_valid"].max()
    title = lvmin.strftime("%-d %b %Y")
    if lvmin.date() != lvmax.date():
        title = "%s - %s" % (
            lvmin.strftime("%-d %b %Y"),
            lvmax.strftime("%-d %b %Y"),
        )
    return title


def make_precip_plot(ctx):
    """Generate a precip plot, please."""
    df = ctx["df"]
    # Accumulate the precipitation
    df["precip_accum"] = df["precip"].cumsum()
    df["precip_rate1"] = df["precip"] * 60.0
    df["precip_rate15"] = df["precip"].rolling(window=15).sum() * 4.0
    df["precip_rate60"] = df["precip"].rolling(window=60).sum()
    (fig, ax) = plt.subplots(1, 1, figsize=(8, 6))
    ax.set_position([0.06, 0.14, 0.77, 0.78])

    ax.bar(
        df["local_valid"].values,
        df["precip_rate1"],
        width=1.0 / 1440.0,
        color="b",
        label="Hourly Rate over 1min",
        zorder=1,
    )
    ax.plot(
        df["local_valid"].values,
        df["precip_rate15"],
        color="tan",
        label="Hourly Rate over 15min",
        linewidth=3.5,
        zorder=3,
    )
    ax.plot(
        df["local_valid"].values,
        df["precip_rate60"],
        color="r",
        label="Actual Hourly Rate",
        lw=3.5,
        zorder=3,
    )
    ax.plot(
        df["local_valid"].values,
        df["precip_accum"],
        color="k",
        label="Accumulation",
        lw=3.5,
        zorder=3,
    )

    # Find max precip
    df2 = df[df["precip"] == df["precip"].max()]
    if not df2.empty:
        idx = df2.index.values[0]
        x = 1.02
        y = 0.95
        ax.text(
            x,
            y,
            "1 Minute Precip\nNear Peak Rate",
            transform=ax.transAxes,
            bbox=dict(fc="white", ec="None"),
        )
        y -= 0.06
        for i in range(max([0, idx - 8]), idx + 8):
            row = df.iloc[i]
            ax.text(
                x,
                y,
                "%s %.2f"
                % (row["local_valid"].strftime("%-I:%M %p"), row["precip"]),
                transform=ax.transAxes,
                fontsize=10,
                bbox=dict(fc="white", ec="None"),
            )
            y -= 0.04

    ax.set_ylabel("Precipitation Rate [inch/hour]")
    ax.grid(True)
    ax.legend(loc=1, ncol=1)
    ymax = max([7, df["precip_accum"].max(), df["precip_rate1"].max()])
    ax.set_ylim(0, int(ymax + 1))
    ax.set_yticks(range(0, int(ymax + 1), 1))
    ax.set_title(
        (
            f"{get_ttitle(df)} %s (%s)\n"
            "One Minute Rainfall, "
            "%.2f inches total plotted, %s missing minutes"
        )
        % (
            ctx["_nt"].sts[ctx["zstation"]]["name"],
            ctx["zstation"],
            df["precip_accum"].max(),
            df["precip"].isna().sum(),
        )
    )
    do_xaxis(ctx, ax)
    ax.set_xlim(df["local_valid"].min(), df["local_valid"].max())
    return fig


def plotter(fdict):
    """ Go """
    ctx = get_autoplot_context(fdict, get_description())
    if "HAS1MIN" not in ctx["_nt"].sts[ctx["zstation"]]["attributes"]:
        raise NoDataFound("Sorry, the IEM has no one-minute data for station.")
    # Make timestamps tzaware
    for col in ["sts", "ets"]:
        ctx[col] = ctx[col].replace(tzinfo=timezone.utc)
    if (ctx["ets"] - ctx["sts"]) > timedelta(days=5):
        raise ValueError("Too much data requested, only < 5 days supported.")
    ctx["df"] = get_data(ctx)

    if ctx["ptype"] == "precip":
        fig = make_precip_plot(ctx)
    elif ctx["ptype"] in ["wind", "windkt"]:
        fig = make_wind_plot(ctx, ctx["ptype"])
    # Need to drop timezone for excel output
    for col in ["utc_valid", "local_valid"]:
        ctx["df"][col] = ctx["df"][col].dt.tz_localize(None)
    return fig, ctx["df"]


if __name__ == "__main__":
    plotter(
        {
            "network": "PA_ASOS",
            "zstation": "RDG",
            "sts": "2020-08-02 0900",
            "ets": "2020-08-02 1245",
        }
    )
