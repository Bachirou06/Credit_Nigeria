# CREDIT_layer — Nigeria
The **Creating the Custom Residential Electricity Demand Indicative Target (CREDIT)** layer as presented in this [open access publication](https://www.mdpi.com/1996-1073/12/7/1395).

> **This repository has been adapted for Nigeria (NGA).**
> Original code was developed for Guinea (GIN). Key changes: country boundary → NGA, admin-2 LGA level (~774 LGAs),
> UTM projection → EPSG:32632 (WGS84 / UTM zone 32N), GDP raster → Kummu v4 2024 clipped to Nigeria,
> MTF demand targets from ESMAP "Nigeria: Beyond Connections" (2018), HH size ~5.1 people:
> min 0.9 kWh/capita/year (Tier 1), max 588 kWh/capita/year (Tier 5).
> Poverty data: OPHI MPI at LGA (ADM2) level, available on HDX (`nigeria-mpi`).

Predicting electricity demand in currently un-electrified settlement is a challenge. Many energy access efforts use the multi-tier framework (MTF) as a point of reference; OnSSET in particular, uses this approach as it provides a good basis of (investment) comparison between different levels of access. Access tiers are assigned to settlements based on selection criteria; the most common approach (also adopted in GEP) is to assign tier-targets to urban/rural settlements respectively. This approach allows for limited spatial allocation of targets let alone it does not take into account newly available spatial information.

The Custom Residential Electricity Demand Indicative Target (CREDIT) has been developed so as to provide a spatially explicit, alternative approach of predicting electricity demand targets in currently un-electrified settlements, by using poverty and GDP maps.

First, we collect available data for each country. We use the national GDP, PPP (purchasing-power-parity) values for 2015 in constant 2011 U.S. dollars (USD) . Poverty maps are acquired from the WorldPop database in raster format, where available.  Else, tabular data available on administrative level are used as provided by the World Bank. Values used, indicate the share of population living below the poverty line (defined as $2/day). 

The second step on the process requires that both - poverty and GDP - maps are re-classified using a 1-5 scale as shown in the table below. 

| Initial   poverty layer | Classification| Initial GDP layer | Classification |
|-------------------------|---------------|-------------------|----------------|
| 0 ≤   pov. rate < 0.2   | 5             | I1 ≤ GDP < I3     | 1              |
| 0.2 ≤   pov. rate < 0.4 | 4             | I2 ≤ GDP < I3     | 2              |
| 0.4 ≤   pov. rate < 0.6 | 3             | I3 ≤ GDP < I4     | 3              |
| 0.6 ≤   pov. rate < 0.8 | 2             | I4 ≤ GDP < I5     | 4              |
| pov. rate ≥   0.8       | 1             | GDP ≥ I5          | 5              |

The poverty map is classified using the equal interval method. The GDP map using natural breaks mentod. The classification method can have an impact on the final product layer. Please make sure you understand the differences between the methods and select the one that suits best in your case. The output map gives a “suitability” index that varies from 1-5; 1 suggesting low demand target and 5 suggesting high demand target.  

![AHP_result](https://github.com/global-electrification-platform/CREDIT_layer/blob/master/sample_output/AHP_result_option_2.png)

In order to translate this into an electricity demand target, we use 1-D linear interpolation, using min/max demand values. These, are based on MTF adapted to reflect the situation in each country (different household size  per country). That is, the lowest and highest values for e.g. Malawi were set at 8.8 and 680.2 kWh/capita/year for Malawi. We have chosen this approach as it provide consistency between the modelled countries.

![Sample_result](https://github.com/global-electrification-platform/CREDIT_layer/blob/master/sample_output/Sample_CREDIT_result.png)

---

**Note!** This approach does not predict electricity demand since is not based on regression. It is simply a improved approach of geospatially distributing tier-based targets based on available geospatial information. Research is active in the field     so we expect that new data, results, maps and methods will be available in the next phase of the project.

---

