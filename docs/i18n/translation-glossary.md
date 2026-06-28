# Albiz Translation Glossary

This glossary defines preferred English to Albanian terminology for the Albiz analytics app.

Use clear academic Albanian. Keep terminology consistent across methodology, dashboard, reports, and ML pages.

## Core Terms

| English | Albanian |
| --- | --- |
| Albiz analytics app | Aplikacioni analitik Albiz |
| APP procurement data | Të dhënat e prokurimit nga APP |
| QKB registry data | Të dhënat e regjistrit nga QKB |
| QKB registry layer | Shtresa e regjistrit QKB |
| Registry backbone | Baza kryesore e regjistrit |
| Joined dataset | Dataset i bashkuar |
| Joined APP-QKB companies | Kompani të bashkuara APP-QKB |
| Exact NIPT matching | Përputhje e saktë e NIPT-it |
| Exact normalized NIPT matching | Përputhje e saktë e NIPT-it të normalizuar |
| Exact normalized name difference | Diferencë në emrin e normalizuar saktësisht |
| Data pipeline | Tubacion i të dhënave |
| Data quality | Cilësia e të dhënave |
| Data completeness | Plotësia e të dhënave |
| Coverage | Mbulimi |
| Registry coverage | Mbulimi i regjistrit |
| Missing values | Vlera të munguara |
| Source availability | Disponueshmëria e burimit |

## Procurement and Performance Terms

| English | Albanian |
| --- | --- |
| Procurement-based performance proxy | Përafërues i performancës së bazuar në prokurime |
| Procurement activity | Aktiviteti i prokurimit |
| Procurement profile | Profili i prokurimit |
| Winner value | Vlera fituese |
| Budget limit | Kufiri buxhetor |
| Winner/Budget ratio | Raporti fitues/buxhet |
| Active procurement count | Numri i prokurimeve aktive |
| Cancelled procurement rate | Norma e prokurimeve të anuluara |
| Suspended procurement rate | Norma e prokurimeve të pezulluara |
| Contracting authority | Autoritet kontraktor |
| Procedure type | Lloji i procedurës |
| Contract type | Lloji i kontratës |

## Risk and Indicator Terms

| English | Albanian |
| --- | --- |
| Analytical risk indicators | Tregues analitikë të riskut |
| Procurement anomaly indicators | Tregues të anomalive në prokurim |
| Risk indicator count | Numri i treguesve të riskut |
| Indicator distribution | Shpërndarja e treguesve |
| Indicator concentration | Përqendrimi i treguesve |
| Analytical signals | Sinjale analitike |
| Unusual procurement profile | Profil i pazakontë prokurimi |
| Statistical outlier | Vlerë statistikisht e veçuar |
| Human review required | Kërkohet shqyrtim njerëzor |
| Not evidence of misconduct | Nuk është provë e sjelljes së parregullt |
| Not a legal determination | Nuk është përcaktim ligjor |
| Not intended for automated decisions | Jo i synuar për vendimmarrje të automatizuar |

## Machine Learning Terms

| English | Albanian |
| --- | --- |
| Exploratory ML analysis | Analizë eksploruese me mësim makinerik |
| Exploratory machine learning | Mësim makinerik eksplorues |
| Heuristic weak label | Etiketë e dobët heuristike |
| Strict weak label | Etiketë e dobët strikte |
| Weak-label replication | Riprodhim i etiketës së dobët |
| Heuristic consistency | Konsistencë heuristike |
| Reduced-feature model | Model me veçori të reduktuara |
| Reduced-feature strict-label model | Model me veçori të reduktuara dhe etiketë strikte |
| Anomaly detection | Zbulimi i anomalive |
| Anomaly ranking | Renditje e anomalive |
| Clustering | Grupëzim |
| Cluster summary | Përmbledhje e grupëzimit |
| PCA visualization | Vizualizim me PCA |
| PCA projection | Projektim PCA |
| Dimensionality reduction | Reduktim i dimensionalitetit |
| Feature matrix | Matrica e veçorive |
| Feature importance | Rëndësia e veçorive |
| Confusion matrix | Matrica e konfuzionit |
| Model stability | Stabiliteti i modelit |
| Benchmark Suite | Suitë vlerësimi krahasues |
| Repeated cross-validation | Validim i kryqëzuar i përsëritur |
| Average precision | Precizion mesatar |
| PR AUC | Sipërfaqja nën kurbën precizion-rikujtim |
| ROC AUC | Sipërfaqja nën kurbën ROC |
| Balanced accuracy | Saktësi e balancuar |
| Model card | Kartë e modelit |
| Leakage/circularity risk | Rrezik rrjedhjeje/cirkulariteti |

## Financial Enrichment Terms

| English | Albanian |
| --- | --- |
| Secondary financial enrichment | Pasurim financiar dytësor |
| OpenCorporates financial subset | Nën-bashkësi financiare nga OpenCorporates |
| Exploratory financial data | Të dhëna financiare eksploruese |
| Financial subset experiment | Eksperiment i nën-bashkësisë financiare |
| Financial enrichment experiment | Eksperiment i pasurimit financiar |
| Procurement-only baseline | Bazë krahasuese vetëm me prokurime |
| Procurement plus financial enrichment | Prokurime plus pasurim financiar |
| Financial coverage | Mbulim financiar |
| Revenue amount | Shuma e të ardhurave |
| Profit before tax | Fitimi para tatimit |
| Latest financial year | Viti më i fundit financiar |
| Financial year availability | Disponueshmëria sipas viteve financiare |
| Validate against official filings where required | Të validohet kundrejt depozitimeve zyrtare kur kërkohet |

## Source and Entity Names That Should Not Be Translated

Keep these unchanged:

- Albiz
- APP
- QKB
- NIPT
- NUIS
- OpenCorporates
- Django
- Velzon
- ApexCharts
- Plotly
- scikit-learn
- Logistic Regression
- Random Forest
- ExtraTrees
- Gradient Boosting
- HistGradientBoosting
- Isolation Forest
- Local Outlier Factor
- KMeans
- PCA

## Terms to Avoid

Avoid these terms unless quoting an external source or describing a limitation:

- fraud
- corruption
- confirmed violation
- accusation
- proven risk
- official verified financial statements
- complete national financial panel
- financial data proves risk
- high-risk company
- risk score

Preferred alternatives:

- analytical risk indicators
- indicator count
- unusual procurement profile
- secondary financial enrichment
- heuristic weak label
- exploratory result
- procurement-based performance proxy
