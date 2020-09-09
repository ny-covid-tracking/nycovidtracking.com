import json
import pandas as pd
import os
import sys

from datetime import datetime, timedelta
from sodapy import Socrata


print("Updating covid data")

if not (token := os.environ.get("SODAPY_APPTOKEN")):
    raise EnvironmentError("SODAPY_APPTOKEN not set")

domain = "data.ny.gov"
covid_id = "xdss-u53e"

client = Socrata(domain, token)

site_last_updated = 0
if "site-last-updated" in os.listdir("."):
    with open("site-last-updated", "r") as f:
        site_last_updated = int(f.read())

metadata = client.get_metadata(covid_id)
if data_last_updated := metadata.get("rowsUpdatedAt"):
    data_last_updated = int(data_last_updated)
    if site_last_updated >= data_last_updated:
        sys.exit(0)

testing_data = client.get_all(covid_id, select="county, test_date, new_positives")


print("Cleaning data")

testing_data = [
    {
        "county": c["county"].lower(),
        "test_date": datetime.strptime(c["test_date"], "%Y-%m-%dT%H:%M:%S.%f"),
        "new_positives": int(c["new_positives"]),
    }
    for c in testing_data
]

with open("ny-county-populations-2019.csv", "r") as f:
    population_data = [r.split(",") for r in f.read().strip().split("\n")][1:]

population_data = [
    {
        "county": r[0],
        "population": int(r[1])
    }
    for r in population_data
]


print("Joining data and calculating stats")

df_testing = pd.DataFrame(testing_data)
df_population = pd.DataFrame(population_data)

df_testing = pd.merge(df_testing, df_population, on="county")

total_cases = df_testing["new_positives"].sum()
overall_summary = {"total_cases": int(total_cases)}

max_date = df_testing["test_date"].max()
one_week_date = max_date - timedelta(days=7)
two_week_date = max_date - timedelta(days=14)

df_avg_new_daily_cases = df_testing[df_testing["test_date"] > one_week_date]
overall_summary["last_week_cases"] = int(df_avg_new_daily_cases["new_positives"].sum())
df_avg_new_daily_cases = df_avg_new_daily_cases.groupby("county")["new_positives"].mean().reset_index()
df_avg_new_daily_cases = df_avg_new_daily_cases.rename(columns={"new_positives": "avg_new_daily_cases"})

df_avg_prior_daily_cases = df_testing[(df_testing["test_date"] > two_week_date) & (df_testing["test_date"] <= one_week_date)]
df_avg_prior_daily_cases = df_avg_prior_daily_cases.groupby("county")["new_positives"].mean().reset_index()
df_avg_prior_daily_cases = df_avg_prior_daily_cases.rename(columns={"new_positives": "avg_prior_daily_cases"})

df_county_stats = df_testing[df_testing["test_date"] == max_date]
overall_summary["yesterday_cases"] = int(df_county_stats["new_positives"].sum())
df_county_stats = pd.merge(df_county_stats, df_avg_new_daily_cases, on="county")
df_county_stats = pd.merge(df_county_stats, df_avg_prior_daily_cases, on="county")

df_county_stats["avg_new_daily_cases_rate"] = df_county_stats["avg_new_daily_cases"] / df_county_stats["population"]
df_county_stats["avg_new_daily_cases_rate_per_100k"] = df_county_stats["avg_new_daily_cases"] / df_county_stats["population"] * 100000

df_county_stats["avg_prior_daily_cases_rate"] = df_county_stats["avg_prior_daily_cases"] / df_county_stats["population"]
df_county_stats["avg_prior_daily_cases_rate_per_100k"] = df_county_stats["avg_prior_daily_cases"] / df_county_stats["population"] * 100000

ranks = df_county_stats.sort_values("avg_new_daily_cases_rate_per_100k", ascending=True)
best_5 = ranks.head(5)
ranks = df_county_stats.sort_values("avg_new_daily_cases_rate_per_100k", ascending=False)
worst_5 = ranks.head(5)


print("Joining stats with GeoJSON")

with open("ny-counties-geo.json", "r") as f:
    geojson = json.load(f)

for i in range(len(geojson["features"])):
    county = geojson["features"][i]["properties"]["NAME"].lower()
    row = df_county_stats[df_county_stats["county"] == county]
    geojson["features"][i]["properties"]["new_positives"] = int(row.iloc[0]["new_positives"])
    geojson["features"][i]["properties"]["population"] = int(row.iloc[0]["population"])
    geojson["features"][i]["properties"]["avg_new_daily_cases"] = round(row.iloc[0]["avg_new_daily_cases"], 2)
    geojson["features"][i]["properties"]["avg_prior_daily_cases"] = round(row.iloc[0]["avg_prior_daily_cases"], 2)
    geojson["features"][i]["properties"]["avg_new_daily_cases_rate"] = round(row.iloc[0]["avg_new_daily_cases_rate"], 2)
    geojson["features"][i]["properties"]["avg_new_daily_cases_rate_per_100k"] = round(row.iloc[0]["avg_new_daily_cases_rate_per_100k"], 2)
    geojson["features"][i]["properties"]["avg_prior_daily_cases_rate"] = round(row.iloc[0]["avg_prior_daily_cases_rate"], 2)
    geojson["features"][i]["properties"]["avg_prior_daily_cases_rate_per_100k"] = round(row.iloc[0]["avg_prior_daily_cases_rate_per_100k"], 2)


print("Saving GeoJSON")

with open("ny-counties-geo.js", "w") as f:
    f.write("var countiesData = ")
    f.write(json.dumps(geojson))
    f.write(";")

with open("overall.js", "w") as f:
    f.write("var overallData = ")
    f.write(json.dumps(overall_summary))
    f.write(";")

with open("best_5.js", "w") as f:
    f.write("var best5Data = ")
    f.write(json.dumps(best_5[["county", "avg_new_daily_cases_rate_per_100k"]].to_dict('records')))
    f.write(";")
    
with open("worst_5.js", "w") as f:
    f.write("var worst5Data = ")
    f.write(json.dumps(worst_5[["county", "avg_new_daily_cases_rate_per_100k"]].to_dict('records')))
    f.write(";")


print("Updating site-last-updated")

with open("site-last-updated", "w") as f:
    f.write(str(data_last_updated))
