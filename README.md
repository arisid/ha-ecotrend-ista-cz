# ista EcoTrend (CZ / Nordic) – custom integrace pro Home Assistant

Neoficiální integrace pro **novou** verzi portálu ista Ecotrend na
`https://ecotrend.ista.cz` (Unity-WebGL aplikace, backend
`prod.istaonlinebeta.dk` / `graphs.istaonlinebeta.dk`, Keycloak realm
`eed-nordic`).

⚠️ Toto **není** totéž jako klasická appka "ista EcoTrend"
(`api.prod.eed.ista.com`, realm `eed-prod`), pro kterou už existuje
komunitní integrace (`Ludy87/ecotrend-ista`, knihovna `pyecotrend-ista`).
Český `ecotrend.ista.cz` běží na jiném, novějším Nordic backendu, takže
tahle integrace je napsaná od nuly na základě rozboru HAR záznamu z
prohlížeče.

## Co to umí

Po přihlášení vytvoří pro každý měřič z `GET /api/Meters` jeden senzor
(v našem případě: **Teplá voda**, **Studená voda**, **Energie**) se
stavem = poslední odečet, jednotkou m³ / kWh a `state_class:
total_increasing` – takže jde rovnou zapojit do Energy dashboardu.
Ke každému senzoru se přidá i poslední spotřeba, datum odečtu, číslo
měřiče a místnost jako atributy.

## Historie spotřeby (Energy dashboard)

Všechny tři senzory (**Energie**, **Teplá voda**, **Studená voda**) si
při prvním načtení jednorázově natáhnou zpětnou měsíční historii z
`graphs.istaonlinebeta.dk` a nahrají ji do dlouhodobých statistik Home
Assistanta (`recorder`) – takže se v Energy dashboardu rovnou zobrazí i
historie zpětně, ne jen to, co HA napočítá od instalace integrace.
Endpointy (`Usage_Energy_Data`, `Usage_WaterHot_Data`,
`Usage_WaterCold_Data`, vše s `inverval=3` pro měsíční krok) i chování
`formerPeriode` (srovnání s předchozím rokem, dostupné jako součást
každého bodu) jsme ověřili proti HAR záznamu z proklikání všech
možností zobrazení (den/týden/měsíc/rok) pro všechny tři měřiče.

**Výměna fyzického vodoměru:** vodoměry se běžně po letech fyzicky
vyměňují (kalibrace) a historie u ista jede napříč výměnami, zatímco
aktuální odečet patří jen tomu současnému kusu. Integrace to řeší tak,
že do importované historie bere jen měsíce od `Activation_date`
aktuálního měřiče dál (to už teď vidíš i jako atribut u senzoru) –
jinak by se v grafu objevily nesmyslné záporné hodnoty z období starého
měřiče. Otestováno na reálných datech (u tvého účtu šlo přesně o tenhle
případ, oba vodoměry mají `Activation_date` 2024-09-18).

⚠️ **Menší nejistota navíc:** `graphs.istaonlinebeta.dk` je oddělená
podaplikace od hlavního API (`prod.istaonlinebeta.dk`), kterou jsme
v zachyceném provozu viděli používat vlastní, jinak vydaný token. Oba
tokeny ale patří stejnému uživateli, stejnému Keycloak realmu i
klientovi, takže integrace zkouší použít náš běžný přístupový token i
tady – to ale nebylo ověřeno přímo proti živému účtu (na rozdíl od
zbytku integrace, který přes reálná data prošel). Pokud by ista tohle
odmítala, historie se prostě nenačte (do logu půjde varování), ale
**aktuální hodnoty senzorů tím nejsou nijak ovlivněné** – to jsme
otestovali explicitně, včetně scénáře, kdy uspěje jen část měřičů.

Import proběhne jen jednou za život dané instalace (eviduje se v
konfiguraci integrace) – při dalších restartech/reloadech se
`graphs.istaonlinebeta.dk` znovu nevolá.

## Logo / ikona

Integrace má vlastní `brand/` složku (`icon.png`, `icon@2x.png`,
`logo.png`, `logo@2x.png`) – od Home Assistant **2026.3** stačí tohle
mít přímo v balíčku integrace a HA logo samo zobrazí v Nastavení →
Zařízení a služby i na stránce zařízení, přes nové lokální API
`/api/brands/integration/…` (žádná registrace ani zásah do
`manifest.json` navíc není potřeba – funguje to automaticky podle
názvu domény). Na starším HA (< 2026.3) integrace poběží úplně stejně,
jen bez loga – nic se tím nerozbije.

⚠️ **V HACS seznamu před instalací se logo nezobrazí** – to není
řešitelné úpravou balíčku. Je to potvrzený otevřený bug v samotném
HACS ([hacs/integration#5171](https://github.com/hacs/integration/issues/5171)):
HACS si logo pro svůj přehled tahá z vlastního CDN
(`data-v2.hacs.xyz`), které se plní ze starého repozitáře
`home-assistant/brands` – ten ale od HA 2026.3 pro custom integrace
noví PR vůbec nepřijímá (nahradila ho právě tahle lokální `brand/`
složka). HACS zatím neumí spadnout zpátky na lokální HA API. Jakmile to
HACS opraví, logo se objeví samo bez jakékoli změny u nás.

## Zveřejnění na vlastním GitHubu (pro instalaci přes HACS)

1. Založ nové **veřejné** repo na GitHubu (např. `ha-ecotrend-ista-cz`).
2. Nahraj do něj obsah tohoto zipu tak, jak je (`custom_components/`,
   `hacs.json`, `README.md`, `LICENSE` v kořeni repa).
3. `manifest.json` už má vyplněné `codeowners`/`documentation`/`issue_tracker`
   na `github.com/arisid/ha-ecotrend-ista-cz` – při aktualizaci existujícího
   repa nic měnit nemusíš, jen nahraj nové soubory (přepíší staré).
4. Vytvoř Release s tagem odpovídajícím `version` v manifestu (aktuálně
   `v0.3.0`) – HACS podle releasů/tagů verzuje a pozná, že je k dispozici
   update.
5. V Home Assistantu: HACS → ⋮ vpravo nahoře → **Custom repositories** →
   vlož URL svého repa → kategorie **Integration** → Add.
6. Integrace se objeví v HACS ke stažení; po instalaci restartuj HA a
   přidej ji přes Nastavení → Zařízení a služby, jak popsáno níž.

## Instalace

### Přes HACS (doporučeno)
1. HACS → tři tečky vpravo nahoře → **Custom repositories**
2. Přidej URL tohoto repozitáře, kategorie **Integration**
3. Nainstaluj "ista EcoTrend (CZ / Nordic)" a restartuj Home Assistant

### Ručně
Zkopíruj složku `custom_components/ecotrend_ista_cz` do
`<config>/custom_components/` a restartuj Home Assistant.

### Nastavení
Nastavení → Zařízení a služby → Přidat integraci → „ista EcoTrend (CZ /
Nordic)" → zadej stejné uživatelské jméno a heslo, jaké používáš na
ecotrend.ista.cz.

V Možnostech integrace (ozubené kolo na kartě integrace) lze změnit
interval aktualizace (výchozí 60 minut – odečty se na portálu stejně
neaktualizují víc než cca jednou denně, takže není důvod stahovat
častěji).

## ⚠️ Jedna neznámá v přihlašování – čti, prosím

Přihlašovací `POST /token` posílá kromě `username`/`password` ještě dvě
pole, `value1` (32 bajtů) a `value2` (48 bajtů), zakódovaná jako
`_46_190_76_..._`. Tahle pole generuje samotný zkompilovaný
Unity/WebAssembly klient a z HAR záznamu nejde spolehlivě zjistit, jak
přesně se počítají (byl by potřeba reverse engineering .wasm binárky).

Nejpravděpodobnější vysvětlení je, že jde jen o telemetrii/otisk
zařízení pro detekci podvodů na straně serveru, ne o kryptografický
podpis, který se ověřuje – ostatní pole (`username`, `password`) totiž
chodí normálně v čitelné podobě. Integrace proto posílá **náhodná**
data ve stejném tvaru (32, resp. 48 čísel 0–255).

**Pokud přihlášení selže** (chyba `invalid_auth` i se správným heslem):

1. Zapni si debug log v `configuration.yaml`:
   ```yaml
   logger:
     logs:
       custom_components.ecotrend_ista_cz: debug
   ```
2. Zkus se znovu přihlásit a podívej se do logu, co přesně ista vrátila
   (status kód a tělo odpovědi z `/token`).
3. Nejlépe pořiď čerstvý HAR záznam **jen** přihlašovacího requestu
   (Chrome DevTools → Network → „Preserve log“ → přihlásit se na
   ecotrend.ista.cz → Export HAR) a porovnej `value1`/`value2` s
   předchozím – pokud se mění i mezi dvěma přihlášeními **stejného**
   prohlížeče/účtu, pravděpodobně jde jen o náhodná/perzistentní data
   zařízení a chybu způsobuje něco jiného. Napiš mi znovu s tímhle
   novým HAR a doladíme to.

## Odhlašování

V zachyceném provozu odhlášení nevolá žádný server endpoint (token
zřejmě jen doexpiruje / se zahodí lokálně), takže integrace žádné
volání při odebrání z Home Assistant neposílá.

## Bezpečnostní poznámka

Uživatelské jméno a heslo se ukládají v konfiguraci Home Assistant
(`config_entries`), stejně jako u jiných cloudových integrací. Refresh
token z odpovědi `/token` integrace využívá k obnovení přístupu bez
nutnosti posílat heslo při každém dotazu.
