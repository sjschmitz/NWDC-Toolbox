"""
NWDC Toolbox
============

python functions for downloading data from the USGS National Water
Availability Assessment Data Companion (NWDC):
https://water.usgs.gov/nwaa-data/

no api key needed.

Every data function uses same inputs:
    location   where:  a state ("ID" or "Idaho"), a county FIPS code
                       ("16001"), or HUC code of any size ("17050114")
    start      first date: a year (2015) or year-month ("2015-06")
    end        last date, same format (leave out to get just one period)
    timestep   "monthly", "calendar_year" or "water_year"

Functions
---------
Find out what is available (works offline):
    list_models()             the datasets (models) and the years they cover
    list_variables()          the variables, their units and their models
    describe(name)            a plain-language description of one item

Download data:
    get_water_use()           irrigation, public supply, thermoelectric use
    get_precipitation()       monthly precipitation
    get_hydrology()           ET, runoff, baseflow, snow, soil moisture, recharge
    get_water_availability()  water availability, streamflow, stress index
    get_data()                any variable(s) by ID, for advanced use


See NWDC_Toolbox_Reference.docx for a full guide.

libs needed: Python 3.9+, pandas, requests
"""

import re
import time
import warnings

import pandas as pd
import requests

__version__ = "0.1.0"

API_URL = "https://api.water.usgs.gov/nwaa-data"


# ---------------------------------------------------------------------------
# Find out what is available
# ---------------------------------------------------------------------------

def list_models(sector=None):
    """List the NWDC datasets (models) and the months they cover.

    Inputs:
        sector  (optional) "use", "quantity" or "availability" to filter
    Returns a table with model_id, model_name, sector, start_date, end_date.
    """
    df = pd.DataFrame(
        [(mid, name, sec, start, end) for mid, (name, sec, start, end, _)
         in MODELS.items()],
        columns=["model_id", "model_name", "sector", "start_date", "end_date"])
    if sector:
        df = df[df["sector"].str.lower().str.contains(sector.lower())]
    return df.reset_index(drop=True)


def list_variables(model=None, sector=None):
    """List the variables you can download, with units and source model.

    Inputs:
        model   (optional) only variables from this model, e.g. "prms"
        sector  (optional) "use", "quantity" or "availability"
    Returns a table with variable_id, variable_name, units, model_id, sector,
    start_date, end_date, description. A variable offered by several models
    is listed once per model.
    """
    rows = []
    for vid, (name, units, models, desc) in VARIABLES.items():
        for mid in models:
            _, sec, start, end, _ = MODELS[mid]
            rows.append((vid, name, units, mid, sec, start, end, desc))
    df = pd.DataFrame(rows, columns=["variable_id", "variable_name", "units",
                                     "model_id", "sector", "start_date",
                                     "end_date", "description"])
    if model:
        df = df[df["model_id"] == _model_id(model)]
    if sector:
        df = df[df["sector"].str.lower().str.contains(sector.lower())]
    return df.reset_index(drop=True)


def describe(name):
    """Print a short description of a variable or model.

    Inputs:
        name  a variable ID ("recharge") or model name ("prms", "ensemble")
    """
    key = str(name).strip().lower()
    if key in VARIABLES:
        vname, units, models, desc = VARIABLES[key]
        print(f"{key}: {vname} ({units})\n  {desc}\n  Available from:")
        for mid in models:
            print(f"    {mid}  ({MODELS[mid][2]} to {MODELS[mid][3]})")
    else:
        mid = _model_id(key)
        mname, sector, start, end, summary = MODELS[mid]
        variables = sorted(v for v, info in VARIABLES.items() if mid in info[2])
        print(f"{mid}: {mname}\n  {sector}, {start} to {end}\n"
              f"  Variables: {', '.join(variables)}\n  {summary}")


# ---------------------------------------------------------------------------
# Download data
# ---------------------------------------------------------------------------

def get_water_use(sector, location, start=None, end=None, timestep="monthly",
                  use="withdrawals", source="total"):
    """Download water-use estimates in million gallons per day (Mgal/d).

    Inputs:
        sector    "irrigation", "public_supply" or "thermoelectric"
        location, start, end, timestep   (see top of file)
        use       "withdrawals" (default) or "consumptive_use"
        source    "total" (default), "groundwater", "surface_water" or "all"
    """
    key = (_clean(sector), _clean(use))
    if key not in WATER_USE:
        raise ValueError("sector must be 'irrigation', 'public_supply' or "
                         "'thermoelectric'; use must be 'withdrawals' or "
                         "'consumptive_use'.")
    model, by_source = WATER_USE[key]
    wanted = list(by_source) if _clean(source) == "all" else [_clean(source)]
    if wanted[0] not in by_source:
        raise ValueError(f"source for {sector} {use} must be one of "
                         f"{list(by_source)} or 'all'.")
    variables = [by_source[s] for s in wanted]
    return get_data(variables, location, start, end, timestep, model=model)


def get_precipitation(location, start=None, end=None, timestep="monthly"):
    """Download precipitation in millimeters per month (1979 to 2021).

    Inputs:
        location, start, end, timestep   (see top of file)
    """
    return get_data("precip", location, start, end, timestep,
                    model="wqn-conus404-ba")


def get_hydrology(location, start=None, end=None, timestep="monthly",
                  variables="all", model="ensemble"):
    """Download modeled water-budget values (ET, runoff, snow, recharge...).

    Inputs:
        location, start, end, timestep   (see top of file)
        variables  "all" (default) or any of: actet, incbsflow, incqkflow,
                   incrunoff, swe, soilmstfr, and (prms / wrf-hydro only)
                   soilmst, recharge
        model      "ensemble" (default, 2009-2020), "prms" (1983-2021) or
                   "wrf-hydro" (2009-2021)
    """
    if isinstance(variables, str) and variables.lower() == "all":
        mid = _model_id(model)
        variables = [v for v, info in VARIABLES.items() if mid in info[2]]
    return get_data(variables, location, start, end, timestep, model=model)


def get_water_availability(location, start=None, end=None, timestep="monthly",
                           variables="all"):
    """Download water availability results from the 2025 national assessment.

    Inputs:
        location, start, end, timestep   (see top of file)
        variables  "all" (default) or any of: availab, strflow, consum, sui
    """
    if isinstance(variables, str) and variables.lower() == "all":
        variables = ["availab", "strflow", "consum", "sui"]
    return get_data(variables, location, start, end, timestep,
                    model="iwa-assessment-outputs-conus-2025")


def get_data(variables, location, start=None, end=None, timestep="monthly",
             model=None, intersection="overlap"):
    """Download any variable(s) by ID. The other get_ functions use this.

    Inputs:
        variables     one ID ("pswdtot") or a list (["pswdgw", "pswdsw"]);
                      all must come from the same model
        location, start, end, timestep   (see top of file)
        model         needed only when several models have the variable
                      ("ensemble", "prms", "wrf-hydro")
        intersection  "overlap" (default): HUC12s touching the area;
                      "envelop": only HUC12s fully inside it
    Returns one row per HUC12 and date, with one column per variable.
    """
    variables = _variable_list(variables)
    model_id = _pick_model(variables, model)
    timeres = _timestep(timestep)
    if end is None:
        end = start
    start_s = _date(start, timeres, is_end=False)
    end_s = _date(end, timeres, is_end=True)
    _check_dates(model_id, start_s, end_s)

    params = {"model": model_id, "variable": ",".join(variables),
              "location": _location(location), "timeres": timeres,
              "startdate": start_s, "enddate": end_s,
              "intersection": intersection, "format": "json", "limit": PAGE_SIZE}

    # The API returns up to PAGE_SIZE HUC12s at a time; keep asking until done.
    rows, units, skip = [], {}, 0
    while True:
        page = _request("/data", {**params, "skip": skip})
        meta = page.get("metadata", {})
        units.update(meta.get("units", {}))
        returned = meta.get("recordsReturned", 0)
        rows += _rows_from_page(page, variables)
        skip += returned
        if returned < PAGE_SIZE or skip >= meta.get("totalRecords", 0):
            break

    df = pd.DataFrame(rows, columns=["huc12_id", "date", *variables])
    if df.empty:
        warnings.warn("No data returned for this request.", stacklevel=2)
    df = df.sort_values(["huc12_id", "date"]).reset_index(drop=True)
    df.attrs["units"] = units
    return df


# ---------------------------------------------------------------------------
# Behind the scenes: input clean-up and talking to the API
# ---------------------------------------------------------------------------

PAGE_SIZE = 600  # most HUC12s the API returns per request

TIMESTEPS = {
    "monthly": "monthly", "month": "monthly",
    "calendar_year": "annualcy", "annual": "annualcy", "year": "annualcy",
    "annualcy": "annualcy",
    "water_year": "annualwy", "wy": "annualwy", "annualwy": "annualwy",
}

MODEL_NICKNAMES = {
    "ensemble": "wqn-ensemble-conus-nwaa-v1",
    "prms": "wqn-nhmprms-conus-nwaa-v1",
    "nhm-prms": "wqn-nhmprms-conus-nwaa-v1",
    "wrf-hydro": "wqn-wrfhydro-conus-nwaa-v1",
    "wrfhydro": "wqn-wrfhydro-conus-nwaa-v1",
}

# (sector, use): (model, {source: variable})
WATER_USE = {
    ("irrigation", "withdrawals"): ("wu-irrigation-wd", {
        "total": "irrwdtot", "groundwater": "irrwdgw", "surface_water": "irrwdsw"}),
    ("irrigation", "consumptive_use"): ("wu-irrigation-cu", {"total": "irrcutot"}),
    ("public_supply", "withdrawals"): ("wu-public-supply-wd", {
        "total": "pswdtot", "groundwater": "pswdgw", "surface_water": "pswdsw"}),
    ("public_supply", "consumptive_use"): ("wu-public-supply-cu", {"total": "pscutot"}),
    ("thermoelectric", "withdrawals"): ("wu-thermoelectric", {
        "total": "tewdftot", "groundwater": "tewdfgw", "surface_water": "tewdfsw",
        "saline_surface_water": "tewdssw"}),
    ("thermoelectric", "consumptive_use"): ("wu-thermoelectric", {
        "total": "tecuftot", "groundwater": "tecufgw", "surface_water": "tecufsw"}),
}

STATES = {
    "alabama": "AL", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "district of columbia": "DC", "florida": "FL", "georgia": "GA",
    "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME",
    "maryland": "MD", "massachusetts": "MA", "michigan": "MI",
    "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH",
    "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH",
    "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD",
    "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY",
}


def _clean(text):
    return str(text).strip().lower().replace(" ", "_").replace("-", "_")


def _timestep(timestep):
    """'water_year' -> 'annualwy', etc."""
    key = _clean(timestep)
    if key not in TIMESTEPS:
        raise ValueError("timestep must be 'monthly', 'calendar_year' or 'water_year'.")
    return TIMESTEPS[key]


def _date(value, timeres, is_end):
    """Turn 2015, '2015-06', '2015-06-30' or a datetime into the API's format.

    Monthly data needs 'YYYY-MM' (a bare year means Jan for start, Dec for
    end). Annual data needs 'YYYY'; for water years a full date is moved to
    the water year it falls in (Oct-Dec count toward the next year).
    """
    if value is None:
        return None
    if hasattr(value, "year") and hasattr(value, "month"):
        year, month = value.year, value.month
    else:
        match = re.fullmatch(r"(\d{4})(?:[-/](\d{1,2}))?(?:[-/]\d{1,2})?", str(value).strip())
        if not match:
            raise ValueError(f"Can't read date {value!r}; use 2015 or '2015-06'.")
        year = int(match.group(1))
        month = int(match.group(2)) if match.group(2) else None
    if timeres == "monthly":
        month = month or (12 if is_end else 1)
        return f"{year}-{month:02d}"
    if timeres == "annualwy" and month and month >= 10:
        year += 1
    return str(year)


def _location(location):
    """Turn 'Idaho', '16001', '17050114', 'huc8:17050114' into 'type:code'."""
    text = str(location).strip()
    kind, _, code = text.rpartition(":")
    kind = kind.lower()
    if kind in ("state", "statecd") or (not kind and not code.isdigit()):
        abbrev = STATES.get(code.lower(), code.upper())
        if abbrev not in STATES.values():
            raise ValueError(f"Unknown state {code!r}; use a 2-letter code like 'ID'.")
        return f"stateCd:{abbrev}"
    if kind in ("county", "countycd") or (not kind and len(code) == 5):
        if len(code) != 5 or not code.isdigit():
            raise ValueError("County FIPS codes have 5 digits, e.g. '16001'.")
        return f"countyCd:{code}"
    if code.isdigit() and len(code) in (2, 4, 6, 8, 10, 12) and kind in ("", f"huc{len(code)}"):
        return f"huc{len(code)}:{code}"
    raise ValueError(f"Can't read location {location!r}. Use a state ('ID'), "
                     f"county FIPS ('16001') or HUC code ('17050114').")


def _variable_list(variables):
    if isinstance(variables, str):
        variables = variables.split(",")
    variables = [str(v).strip().lower() for v in variables if str(v).strip()]
    unknown = [v for v in variables if v not in VARIABLES]
    if not variables or unknown:
        raise ValueError(f"Unknown variable(s) {unknown}; see list_variables().")
    return list(dict.fromkeys(variables))


def _model_id(model):
    key = MODEL_NICKNAMES.get(str(model).strip().lower(), str(model).strip().lower())
    if key not in MODELS:
        raise ValueError(f"Unknown model {model!r}; see list_models().")
    return key


def _pick_model(variables, model):
    """Find the one model that has all the variables."""
    if model is not None:
        mid = _model_id(model)
        missing = [v for v in variables if mid not in VARIABLES[v][2]]
        if missing:
            raise ValueError(f"{mid} does not have {missing}.")
        return mid
    shared = set.intersection(*(set(VARIABLES[v][2]) for v in variables))
    if len(shared) == 1:
        return shared.pop()
    if not shared:
        raise ValueError("These variables come from different models; "
                         "request them in separate calls.")
    raise ValueError(f"Several models have {variables}; add model='ensemble', "
                     f"'prms' or 'wrf-hydro'.")


def _check_dates(model_id, start, end):
    """Warn when the dates fall outside what the model covers."""
    first, last = MODELS[model_id][2], MODELS[model_id][3]
    if (start and f"{start}-12"[:7] < first) or (end and f"{end}-01"[:7] > last):
        warnings.warn(f"{model_id} covers {first} to {last}; some or all of "
                      f"your dates are outside that range.", stacklevel=3)


def _request(path, params, tries=3):
    """GET from the NWDC API, retrying if the server is busy."""
    for attempt in range(1, tries + 1):
        response = requests.get(API_URL + path, params=params, timeout=300,
                                headers={"User-Agent": f"nwdc-toolbox/{__version__}"})
        if response.ok:
            return response.json()
        if response.status_code in (429, 500, 502, 503, 504) and attempt < tries:
            time.sleep(2 ** attempt)
            continue
        raise RuntimeError(f"NWDC request failed ({response.status_code}): "
                           f"{response.url}\n{response.text[:500]}")


def _rows_from_page(page, variables):
    """Flatten the API's {huc12: [records]} layout into table rows."""
    rows = []
    for huc, records in page.get("data", {}).get("huc12_id", {}).items():
        for record in records:
            # The date key is "year_month" for monthly data, a year key otherwise.
            date = next((record[k] for k in record if k not in variables), None)
            rows.append([str(huc), str(date), *(record.get(v) for v in variables)])
    return rows


# ---------------------------------------------------------------------------
# Catalog of models and variables (from the NWDC data catalog, October 2026)
# ---------------------------------------------------------------------------

# model_id: (name, sector, first month, last month, summary)
MODELS = {
    "wqn-conus404-ba": (
        "Atmospheric Forcing Model (WRF CONUS404-BA)",
        "Water quantity", "1979-10", "2021-09",
        "The WRF CONUS404-BA model provides a retrospective high-resolution hydro-"
        "climate dataset appropriate for forcing hydrological models and conducting "
        "meteorological analyses over the conterminous United States."),
    "wqn-ensemble-conus-nwaa-v1": (
        "Hydrologic Model Ensemble (NHM-PRMS & WRF-Hydro, CONUS NWAA v1)",
        "Water quantity", "2009-10", "2020-09",
        "The NHM-PRMS & WRF-Hydro CONUS NWAA v1 Ensemble model outputs are an average "
        "of results from two component models: NHM-PRMS CONUS NWAA v1 and WRF-Hydro "
        "CONUS NWAA v1."),
    "wqn-nhmprms-conus-nwaa-v1": (
        "Hydrologic Model (NHM-PRMS, CONUS NWAA v1)",
        "Water quantity", "1983-01", "2021-09",
        "The NHM-PRMS CONUS NWAA v1 model application refers to the particular "
        "configuration of the U.S. Geological Survey (USGS) National Hydrologic Model "
        "(NHM) that is currently used to simulate various water quantity components "
        "used in the USGS National Water Availability Assessment (NWAA)"),
    "wqn-wrfhydro-conus-nwaa-v1": (
        "Hydrologic Model (WRF-Hydro, CONUS NWAA v1)",
        "Water quantity", "2009-10", "2021-09",
        "WRF-Hydro is a community-based modeling framework originally designed to "
        "facilitate coupling between the WRF atmospheric model and components of "
        "terrestrial hydrologic models"),
    "wu-irrigation-cu": (
        "Crop Irrigation Consumptive Water-Use Model",
        "Water use", "2000-01", "2020-12",
        "This model computes the amount of water consumed for crop irrigation each "
        "month over the period from 2000 to 2020 for all subwatersheds (12-digit "
        "Hydrologic Unit Codes or HUC12s) in the conterminous United States (CONUS)."),
    "wu-irrigation-wd": (
        "Crop Irrigation Withdrawals Water-Use Model",
        "Water use", "2000-01", "2020-12",
        "Developed to estimate monthly crop irrigation withdrawals from groundwater "
        "and surface water by multiplying modeled irrigation consumptive use "
        "estimates with total irrigation efficiencies, and then applying source-water "
        "proportions."),
    "wu-public-supply-cu": (
        "Public Supply Consumptive Water-Use Model",
        "Water use", "2009-01", "2020-12",
        "This model computes public supply consumptive use each month over the period "
        "from 2009 to 2020 for all subwatersheds (12-digit Hydrologic Unit Codes or "
        "HUC12s) in the conterminous United States (CONUS)."),
    "wu-public-supply-wd": (
        "Public Supply Withdrawals Water-Use Model",
        "Water use", "2000-01", "2020-12",
        "This model computes the amount of water withdrawn for public supply each "
        "month over the period from 2000 to 2020 for all subwatersheds (12-digit "
        "Hydrologic Unit Codes or HUC12s) in the conterminous United States (CONUS)."),
    "wu-thermoelectric": (
        "Thermoelectric Power Water-Use Model",
        "Water use", "2008-01", "2020-12",
        "This model computes the amount of water withdrawn and consumed by "
        "thermoelectric power plants each month over the period from 2008 to 2020 for "
        "all subwatersheds"),
    "iwa-assessment-outputs-conus-2025": (
        "National Water Availability Assessment Outputs (CONUS 2025)",
        "Integrated water availability", "2009-10", "2020-09",
        "These data are outputs of a simple monthly water budget that includes water "
        "supply and consumptive use for thermoelectric, irrigation, and public supply "
        "for HUC12s across CONUS for water years 2010-2020."),
}

# variable_id: (name, units, models that provide it, description)
VARIABLES = {
    "precip": ("Precipitation", "mm/mo",
        ["wqn-conus404-ba"],
        "Precipitation is the total amount of water in the form of rain, freezing "
        "rain, sleet, snow, or hail."),
    "actet": ("Actual evapotranspiration", "mm/mo",
        ["wqn-ensemble-conus-nwaa-v1", "wqn-nhmprms-conus-nwaa-v1", "wqn-wrfhydro-conus-nwaa-v1"],
        "Actual evapotranspiration represents the total flux of water back to the "
        "atmosphere via evaporation and plant transpiration."),
    "incbsflow": ("Incremental baseflow", "mm/mo",
        ["wqn-ensemble-conus-nwaa-v1", "wqn-nhmprms-conus-nwaa-v1", "wqn-wrfhydro-conus-nwaa-v1"],
        "Baseflow is the amount of groundwater flowing to streams."),
    "incqkflow": ("Incremental quickflow", "mm/mo",
        ["wqn-ensemble-conus-nwaa-v1", "wqn-nhmprms-conus-nwaa-v1", "wqn-wrfhydro-conus-nwaa-v1"],
        "Quickflow is the amount of water coming from overland and shallow subsurface "
        "flow."),
    "incrunoff": ("Incremental runoff", "mm/mo",
        ["wqn-ensemble-conus-nwaa-v1", "wqn-nhmprms-conus-nwaa-v1", "wqn-wrfhydro-conus-nwaa-v1"],
        "Runoff is the total amount of water coming from both baseflow and quickflow."),
    "swe": ("Snow water equivalent", "mm",
        ["wqn-ensemble-conus-nwaa-v1", "wqn-nhmprms-conus-nwaa-v1", "wqn-wrfhydro-conus-nwaa-v1"],
        "Snow water equivalent is the depth of water stored in the snowpack in both "
        "liquid and solid forms."),
    "soilmstfr": ("Soil moisture fraction", "frac",
        ["wqn-ensemble-conus-nwaa-v1", "wqn-nhmprms-conus-nwaa-v1", "wqn-wrfhydro-conus-nwaa-v1"],
        "Soil moisture fraction represents relative near-surface soil moisture "
        "volumes, an indicator of how dry or saturated the soil surface is."),
    "soilmst": ("Soil moisture", "mm",
        ["wqn-nhmprms-conus-nwaa-v1", "wqn-wrfhydro-conus-nwaa-v1"],
        "Soil moisture is the depth of water stored in the soil column in both liquid "
        "and solid forms."),
    "recharge": ("Recharge", "mm/mo",
        ["wqn-nhmprms-conus-nwaa-v1", "wqn-wrfhydro-conus-nwaa-v1"],
        "Recharge is the amount of water flowing from surface water to groundwater."),
    "irrwdtot": ("Crop irrigation total withdrawals", "mgd",
        ["wu-irrigation-wd"],
        "The total (groundwater and surface water) amount of water withdrawn for crop "
        "irrigation"),
    "irrwdgw": ("Crop irrigation groundwater withdrawals", "mgd",
        ["wu-irrigation-wd"],
        "The amount of groundwater withdrawn for crop irrigation"),
    "irrwdsw": ("Crop irrigation surface-water withdrawals", "mgd",
        ["wu-irrigation-wd"],
        "The amount of surface water withdrawn for crop irrigation"),
    "irrcutot": ("Crop irrigation total consumptive use", "mgd",
        ["wu-irrigation-cu"],
        "The total (groundwater and surface water) amount of water consumed for crop "
        "irrigation"),
    "pswdtot": ("Public supply total withdrawals", "mgd",
        ["wu-public-supply-wd"],
        "The total (groundwater and surface water) amount of water withdrawn for "
        "public supply"),
    "pswdgw": ("Public supply groundwater withdrawals", "mgd",
        ["wu-public-supply-wd"],
        "The amount of groundwater withdrawn for public supply"),
    "pswdsw": ("Public supply surface-water withdrawals", "mgd",
        ["wu-public-supply-wd"],
        "The amount of surface water withdrawn for public supply"),
    "pscutot": ("Public supply total consumptive use", "mgd",
        ["wu-public-supply-cu"],
        "The total (groundwater and surface water) amount of water consumed for "
        "public supply"),
    "tewdftot": ("Thermoelectric fresh water total withdrawals", "mgd",
        ["wu-thermoelectric"],
        "The amount of fresh water withdrawn for thermoelectric water use"),
    "tewdfgw": ("Thermoelectric fresh groundwater withdrawals", "mgd",
        ["wu-thermoelectric"],
        "The amount of fresh groundwater withdrawn for thermoelectric water use"),
    "tewdfsw": ("Thermoelectric fresh surface-water withdrawals", "mgd",
        ["wu-thermoelectric"],
        "The amount of fresh surface water withdrawn for thermoelectric water use"),
    "tewdssw": ("Thermoelectric saline surface-water withdrawals", "mgd",
        ["wu-thermoelectric"],
        "The amount of saline surface water withdrawn for thermoelectric water use"),
    "tecuftot": ("Thermoelectric fresh water total consumptive use", "mgd",
        ["wu-thermoelectric"],
        "The total (groundwater and surface water) amount of fresh water consumed for "
        "thermoelectric water use"),
    "tecufgw": ("Thermoelectric fresh groundwater consumptive use", "mgd",
        ["wu-thermoelectric"],
        "The amount of fresh groundwater consumed for thermoelectric water use"),
    "tecufsw": ("Thermoelectric fresh surface-water consumptive use", "mgd",
        ["wu-thermoelectric"],
        "The amount of fresh surface water consumed for thermoelectric water use"),
    "availab": ("Total water availability", "mm/mo",
        ["iwa-assessment-outputs-conus-2025"],
        "Total water availability is the total amount of water delivered from one "
        "12-digit hydrologic unit (HUC12) to the next downstream HUC12."),
    "consum": ("Total water consumption", "mm/mo",
        ["iwa-assessment-outputs-conus-2025"],
        "Total water consumption refers to the total amount of water consumed."),
    "strflow": ("Streamflow", "mm/mo",
        ["iwa-assessment-outputs-conus-2025"],
        "Streamflow is the gross cumulative water supply from upstream plus total "
        "water supply generated locally."),
    "sui": ("Surface water supply and use index", "frac",
        ["iwa-assessment-outputs-conus-2025"],
        "The surface water supply and use index (SUI) expresses the fraction of the "
        "long-term water supply that is unavailable either because of climatic "
        "variability or because the water is used consumptively."),
}
