import json
import pandas as pd
import plotly.express as px
import plotly.io as pio
import requests

def get_ny_data(url):
    r = requests.get(url)
    r_json = r.json()
    df = pd.DataFrame(r_json["value"])
    if (next_url := r_json.get("@odata.nextLink")):
        df = pd.concat([df, get_ny_data(next_url)])
    return df

def get_covid_data():
    url = "https://health.data.ny.gov/api/odata/v4/xdss-u53e"
    df = get_ny_data(url)
    df["test_date"] = pd.to_datetime(df["test_date"], format="%Y-%m-%dT%H:%M:%S")
    return df

def get_population_data():
    url = "https://data.ny.gov/api/odata/v4/krt9-ym2k"
    df = get_ny_data(url)
    df = df[df["geography"].str.contains("County")]
    df = df[df["year"] == df["year"].max()]
    df["county"] = df["geography"].str.rsplit(" ", 1).str[0]
    df["fips"] = df["fips_code"].astype("str").str.zfill(5)
    return df

def get_metrics_data(df_cov, df_pop):
    df = pd.merge(df_cov, df_pop, on=["county"])
    df = df.set_index(["county", "test_date"])

    # 7 day moving average infection rate
    df_avg = pd.DataFrame(df.groupby("county").rolling(7)["new_positives"].mean()).reset_index()
    df_avg = df_avg.rename(columns={"new_positives": "new_positives_moving_avg_7d"})
    df_avg.index = pd.MultiIndex.from_tuples(df_avg.level_1, names=["county", "test_date"])
    df = pd.merge(df, df_avg, left_index=True, right_index=True)
    df["new_positives_moving_avg_7d"] = df["new_positives_moving_avg_7d"] / df["population"] * 100_000

    # cumulative infection rate
    df["cumulative_infection_rate"] = df["cumulative_number_of_positives"] / df["population"] * 100_000

    return df

def get_county_geojson():
    url = "https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json"
    r = requests.get(url)
    return r.json()

def get_infection_map(df, geojs):
    df_map = df[["fips", "new_positives_moving_avg_7d"]].reset_index()
    df_map = df_map[df_map["test_date"] == df_map["test_date"].max()]
    df_map["text"] = df_map["new_positives_moving_avg_7d"].round(0)

    fig = px.choropleth(df_map,
                        locations="fips",
                        geojson=geojs,
                        color="new_positives_moving_avg_7d",
                        hover_name="county",
                        hover_data=["text"],
                        labels={
                            "new_positives_moving_avg_7d": "Daily Positive Case Rate per 100k (7 Day Moving Average)",
                            "text": "Daily Positive Case Rate per 100k (7 Day Moving Average)",
                        },
                        color_continuous_scale="thermal",
                        range_color=(
                            df_map["new_positives_moving_avg_7d"].min(),
                            df_map["new_positives_moving_avg_7d"].max()
                        ),
                        scope="usa",
                        title="Daily Positive Case Rate per 100k (7 Day Moving Average)")
    fig.update_geos(fitbounds="locations", visible=False)
    fig.update_layout(coloraxis_colorbar=dict(
        title="",
        ticksuffix=" new cases"),
        template="plotly_dark")

    return fig

def get_infection_ts(df):
    df_ts = df[["cumulative_infection_rate"]].reset_index()

    fig = px.line(df_ts,
                  x="test_date",
                  y="cumulative_infection_rate",
                  line_group="county",
                  color="county",
                  hover_name="county",
                  hover_data=["cumulative_infection_rate"],
                  labels={
                      "county": "County",
                      "cumulative_infection_rate": "Cumulative Infections per 100k",
                      "test_date": "Date",
                  },
                  title="Cumulative Infections per 100k by County")
    fig.update_layout(template="plotly_dark")

    return fig

def populate_template(template, fig_map):
    html = template
    for k, v in fig_map.items():
        fig_html = pio.to_html(v, full_html=False)
        html = html.replace(k, fig_html)
    return html

if __name__ == "__main__":
    df_cov = get_covid_data()
    df_pop = get_population_data()
    df_metrics = get_metrics_data(df_cov, df_pop)
    county_geojson = get_county_geojson()

    infection_map = get_infection_map(df_metrics, county_geojson)
    infection_ts = get_infection_ts(df_metrics)

    with open("index.template") as f:
        index_template = f.read()

    index_html = populate_template(index_template, {
        "{{replace.with.map}}": infection_map,
        "{{replace.with.ts}}": infection_ts,
    })

    with open("index.html", "w") as f:
        f.write(index_html)

