# Sel radarı (Disaster Frontline): ABD sel olaylarını rakipten önce yakalar, Telegram botuyla telefona yazar.
# Saatte bir launchd ile çalışır. Kullanım: python3 sel_radar.py [--dry]
# Kaynaklar: NWS uyarıları (api.weather.gov), NOAA nehir ölçümleri (NWPS), Google Trends ABD, rakip GWN RSS.
import os, sys, shutil, json, re, html, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

D = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(D, 'gorulen_sel.json')
TG = os.path.join(os.path.dirname(D), '_assets', 'telegram_api.txt')
TR = timezone(timedelta(hours=3))  # bulutta (UTC) da TR saati
UA = {'User-Agent': 'DFSelRadar/1.0 (personal news monitor)'}
DRY = '--dry' in sys.argv
NOW = datetime.now(timezone.utc)
DAY = NOW.strftime('%Y-%m-%d')

# Büyük metro çekirdek ilçeleri (NWS areaDesc biçimi "Ilce, ST"). Kural: metro >=500 bin veya ulusal bilinirlik.
METRO = {
 'Los Angeles, CA':'Los Angeles','Orange, CA':'Orange County','San Diego, CA':'San Diego','Riverside, CA':'Riverside',
 'San Bernardino, CA':'San Bernardino','Ventura, CA':'Ventura','Santa Clara, CA':'San Jose','San Francisco, CA':'San Francisco',
 'Alameda, CA':'Oakland','Sacramento, CA':'Sacramento','Fresno, CA':'Fresno','Kern, CA':'Bakersfield',
 'Maricopa, AZ':'Phoenix','Pima, AZ':'Tucson','Clark, NV':'Las Vegas','Washoe, NV':'Reno','Salt Lake, UT':'Salt Lake City',
 'Denver, CO':'Denver','El Paso, CO':'Colorado Springs','Bernalillo, NM':'Albuquerque','El Paso, TX':'El Paso',
 'Harris, TX':'Houston','Fort Bend, TX':'Houston','Montgomery, TX':'Houston','Galveston, TX':'Galveston','Dallas, TX':'Dallas',
 'Tarrant, TX':'Fort Worth','Collin, TX':'Dallas','Denton, TX':'Dallas','Travis, TX':'Austin','Williamson, TX':'Austin',
 'Bexar, TX':'San Antonio','Kerr, TX':'Kerrville','Hidalgo, TX':'McAllen','Cameron, TX':'Brownsville','Nueces, TX':'Corpus Christi',
 'Oklahoma, OK':'Oklahoma City','Tulsa, OK':'Tulsa','Sedgwick, KS':'Wichita','Jackson, MO':'Kansas City','St. Louis, MO':'St. Louis',
 'St. Louis City, MO':'St. Louis','Douglas, NE':'Omaha','Hennepin, MN':'Minneapolis','Cook, IL':'Chicago','DuPage, IL':'Chicago',
 'Milwaukee, WI':'Milwaukee','Wayne, MI':'Detroit','Oakland, MI':'Detroit','Franklin, OH':'Columbus','Cuyahoga, OH':'Cleveland',
 'Hamilton, OH':'Cincinnati','Marion, IN':'Indianapolis','Jefferson, KY':'Louisville','Davidson, TN':'Nashville',
 'Shelby, TN':'Memphis','Knox, TN':'Knoxville','Hamilton, TN':'Chattanooga','Fulton, GA':'Atlanta','DeKalb, GA':'Atlanta',
 'Cobb, GA':'Atlanta','Gwinnett, GA':'Atlanta','Chatham, GA':'Savannah','Jefferson, AL':'Birmingham','Mobile, AL':'Mobile',
 'Orleans, LA':'New Orleans','Jefferson, LA':'New Orleans','East Baton Rouge, LA':'Baton Rouge','Hinds, MS':'Jackson',
 'Pulaski, AR':'Little Rock','Miami-Dade, FL':'Miami','Broward, FL':'Fort Lauderdale','Palm Beach, FL':'West Palm Beach',
 'Hillsborough, FL':'Tampa','Pinellas, FL':'St. Petersburg','Orange, FL':'Orlando','Duval, FL':'Jacksonville',
 'Lee, FL':'Fort Myers','Brevard, FL':'Brevard / Space Coast','Leon, FL':'Tallahassee','Mecklenburg, NC':'Charlotte',
 'Wake, NC':'Raleigh','Buncombe, NC':'Asheville','Charleston, SC':'Charleston','Richland, SC':'Columbia',
 'Fairfax, VA':'Northern Virginia','Virginia Beach City, VA':'Virginia Beach','Norfolk City, VA':'Norfolk',
 'District of Columbia, DC':'Washington DC','Baltimore City, MD':'Baltimore','Philadelphia, PA':'Philadelphia',
 'Allegheny, PA':'Pittsburgh','New York, NY':'New York City','Kings, NY':'Brooklyn','Queens, NY':'Queens','Bronx, NY':'Bronx',
 'Hudson, NJ':'Jersey City','Essex, NJ':'Newark','Suffolk, MA':'Boston','Erie, NY':'Buffalo','King, WA':'Seattle',
 'Pierce, WA':'Tacoma','Snohomish, WA':'Everett','Multnomah, OR':'Portland','Honolulu, HI':'Honolulu','Anchorage, AK':'Anchorage',
 'Coconino, AZ':'Grand Canyon / Flagstaff','Yavapai, AZ':'Sedona / Prescott','Park, WY':'Yellowstone',
}
SEL = re.compile(r'flood|flash flood|storm surge|king tide|atmospheric river|levee|dam (break|fail)|evacuat', re.I)
ABD = re.compile(r'\b(US|U\.S\.|USA|America|Texas|California|Florida|Arizona|Nevada|Georgia|Tennessee|Carolina|Virginia|'
                 r'New York|New Jersey|Louisiana|Mississippi|Alabama|Kentucky|Ohio|Colorado|Utah|Oregon|Washington|Hawaii|'
                 r'Alaska|Oklahoma|Kansas|Missouri|Arkansas|Pennsylvania|Michigan|Illinois|Wisconsin|Minnesota|Iowa|'
                 r'Nebraska|Montana|Idaho|Wyoming|New Mexico|Maryland|Massachusetts|Puerto Rico|' + '|'.join(
                 sorted({re.escape(v.split(' /')[0]) for v in METRO.values()})) + r')\b', re.I)

def get(url, timeout=40):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()

def metrolar(area):
    return sorted({METRO[a.strip()] for a in area.split(';') if a.strip() in METRO})

def nws():
    d = json.loads(get('https://api.weather.gov/alerts/active?status=actual&event=Flash%20Flood%20Warning,Flood%20Warning,Flash%20Flood%20Statement,Coastal%20Flood%20Warning,High%20Surf%20Warning'))
    yigin = {}
    for f in d['features']:
        p = f['properties']; pa = p.get('parameters') or {}
        ev, area, office = p['event'], p['areaDesc'], p.get('senderName', 'NWS')
        if ev in ('Flash Flood Warning', 'Flood Warning'):
            for z in area.split(';'):
                yigin.setdefault(z.strip()[-2:], set()).add(z.strip())
        tehdit = (pa.get('flashFloodDamageThreat') or [''])[0]
        m = metrolar(area)
        url = 'https://forecast.weather.gov/wwamap/wwatxtget.php?cwa=usa&wwa=' + urllib.parse.quote(ev)
        if tehdit == 'CATASTROPHIC':
            yield 10, f'ffe:{office}:{DAY}', '🚨 FLASH FLOOD EMERGENCY', f"{area[:140]} ({office})" + (f" — METRO: {', '.join(m)}" if m else ''), url
        elif m and ev == 'Flash Flood Warning':
            puan = 8 if tehdit == 'CONSIDERABLE' else 6
            yield puan, f"ffw:{'+'.join(m)}:{DAY}", f"⚠️ Flash Flood Warning — {', '.join(m)}" + (' (CONSIDERABLE)' if tehdit == 'CONSIDERABLE' else ''), area[:140], url
        elif ev in ('High Surf Warning', 'Coastal Flood Warning') and not m:
            yield 5, f"kiyi:{ev}:{office}:{DAY}", f"🌊 {ev} — {area.split(';')[0][:60]}", f"{area[:140]} ({office})", url
        elif m and ev in ('Flood Warning', 'Coastal Flood Warning', 'High Surf Warning'):
            yield 5, f"fw:{ev}:{'+'.join(m)}:{DAY}", f"🌊 {ev} — {', '.join(m)}", area[:140], url

    for st, ilc in yigin.items():
        if len(ilc) >= 3:
            yield 6, f"yigin:{st}:{DAY}:{len(ilc) // 3}", f"🌧️ {st}: {len(ilc)} ilçede aynı anda sel uyarısı", '; '.join(sorted(ilc)[:6]), 'https://forecast.weather.gov/wwamap/wwatxtget.php?cwa=usa&wwa=Flash%20Flood%20Warning'

def nwps():
    d = json.loads(get('https://api.water.noaa.gov/nwps/v1/gauges?bbox.xmin=-170&bbox.ymin=17&bbox.xmax=-64&bbox.ymax=72&srid=EPSG_4326', timeout=120))
    major = {}
    for g in d.get('gauges', d):
        st = g.get('status', {})
        obs, fc = st.get('observed', {}).get('floodCategory'), st.get('forecast', {}).get('floodCategory')
        if 'major' in (obs, fc) and not re.search(r'tide|devils lake|stump lake', g['name'], re.I):
            major.setdefault(g['state']['abbreviation'], []).append(g['name'] + ('' if obs == 'major' else ' (tahmin)'))
    for st, names in major.items():
        if len(names) >= 2:
            yield 7, f"nwps:{st}:{DAY}", f"🏞️ {st}: {len(names)} nehir noktası MAJOR taşkında", '; '.join(names[:4]), 'https://water.noaa.gov'

def trends():
    x = ET.fromstring(get('https://trends.google.com/trending/rss?geo=US'))
    ns = {'ht': 'https://trends.google.com/trending/rss'}
    for it in x.iter('item'):
        q = it.findtext('title') or ''
        if SEL.search(q):
            trafik = it.findtext('ht:approx_traffic', '', ns)
            yield 6, f"tr:{q.lower()}:{DAY}", f"📈 Google Trends ABD: '{q}' aranıyor ({trafik})", '', 'https://trends.google.com/trending?geo=US'

RAKIP = {'GWN': 'UCSn-jzJf_LMbT8bAfHj92_Q', 'WeatherWatchUSA': 'UCm9RoJU7rc-bk-3SZzUksdQ'}
def rakip_videolar(cid):
    """Önce YouTube Data API (bulutta tek güvenilir yol), sonra RSS, en son yt-dlp. Son 6 video."""
    key = os.environ.get('YT_API_KEY')
    kf = os.path.join(os.path.dirname(D), '_assets', 'youtube_api_key.txt')
    if not key and os.path.exists(kf):
        key = open(kf).read().strip()
    if key:
        try:
            pl = json.loads(get('https://www.googleapis.com/youtube/v3/playlistItems?part=contentDetails&maxResults=6&playlistId=UU'
                                + cid[2:] + '&key=' + key))
            ids = ','.join(i['contentDetails']['videoId'] for i in pl['items'])
            vs = json.loads(get('https://www.googleapis.com/youtube/v3/videos?part=snippet,statistics&id=' + ids + '&key=' + key))
            return [(v['snippet']['title'], datetime.fromisoformat(v['snippet']['publishedAt'].replace('Z', '+00:00')),
                     int(v['statistics'].get('viewCount', 0)), 'https://www.youtube.com/watch?v=' + v['id']) for v in vs['items']]
        except Exception:
            pass
    ns = {'a': 'http://www.w3.org/2005/Atom'}
    try:
        x = ET.fromstring(get(f'https://www.youtube.com/feeds/videos.xml?channel_id={cid}'))
        out = []
        for e in x.findall('a:entry', ns):
            st = e.find('.//{http://search.yahoo.com/mrss/}statistics')
            out.append((e.findtext('a:title', '', ns), datetime.fromisoformat(e.findtext('a:published', '', ns).replace('Z', '+00:00')),
                        int(st.get('views', 0)) if st is not None else 0, e.find('a:link', ns).get('href')))
        return out
    except Exception:
        import subprocess
        r = subprocess.run([shutil.which('yt-dlp') or os.path.expanduser('~/.local/bin/yt-dlp'), '--skip-download', '--playlist-end', '6', '--no-warnings',
                            '--print', '%(timestamp)s|%(view_count)s|%(webpage_url)s|%(title)s',
                            f'https://www.youtube.com/channel/{cid}/videos'], capture_output=True, text=True, timeout=240)
        out = []
        for l in r.stdout.splitlines():
            ts, v, u, t = l.split('|', 3)
            if ts.isdigit():
                out.append((t, datetime.fromtimestamp(int(ts), timezone.utc), int(v) if v.isdigit() else 0, u))
        if not out:
            raise RuntimeError('rss+yt-dlp boş')
        return out

def rakip():
    for ad, cid in RAKIP.items():
        for t, pub, izl, url in rakip_videolar(cid):
            yas = NOW - pub
            saat = max(yas.total_seconds() / 3600, 0.25)
            # Kullanıcı 11.11: rakipte ~2 saatte 50K-100K olan konu HEMEN bizde yapılır (niş fark etmez)
            if yas <= timedelta(hours=4) and (izl >= 50000 or izl / saat >= 25000):
                yield 20, f"patla:{url}", f"🔥 PATLIYOR — {ad} {izl:,} izlenme / {saat:.1f} saat → HEMEN YAPALIM", t, url

def gonder(mesaj):
    if os.environ.get('TG_BOT_TOKEN'):  # bulut (GitHub Actions secrets)
        cfg = {'bot_token': os.environ['TG_BOT_TOKEN'], 'chat_id': os.environ['TG_CHAT_ID']}
    else:
        cfg = dict(l.strip().split('=', 1) for l in open(TG) if '=' in l)
    veri = urllib.parse.urlencode({'chat_id': cfg['chat_id'], 'text': mesaj, 'parse_mode': 'HTML',
                                   'disable_web_page_preview': 'true'}).encode()
    urllib.request.urlopen('https://api.telegram.org/bot' + cfg['bot_token'] + '/sendMessage', veri, timeout=30).read()

def main():
    try:
        gor = json.load(open(STATE))
    except Exception:
        gor = {}
    ilk = not gor
    yeni, hatalar = [], []
    for kaynak in (nws, nwps, trends, rakip):
        try:
            for puan, key, baslik, detay, url in kaynak():
                if key not in gor:
                    gor[key] = DAY; yeni.append((puan, baslik, detay, url))
        except Exception as e:
            hatalar.append(f'{kaynak.__name__}: {e}')
    # 3 günden eski kayıtları temizle
    sinir = (NOW - timedelta(days=3)).strftime('%Y-%m-%d')
    gor = {k: v for k, v in gor.items() if k.startswith('_') or v >= sinir}
    yeni.sort(key=lambda x: -x[0])
    zaman = datetime.now(TR).strftime('%d.%m %H:%M')
    if yeni:
        parca = [f'🌧️ <b>SEL RADARI</b> {zaman}' + (' (ilk tarama, şu an açık olanlar)' if ilk else '')]
        for puan, b, dt, u in yeni[:12]:
            parca.append(f'\n<b><a href="{html.escape(u)}">{html.escape(b)}</a></b>' + (f'\n{html.escape(dt)}' if dt else ''))
        mesaj = '\n'.join(parca)
        print(mesaj)
        if not DRY:
            gonder(mesaj[:4000])
    else:
        print(zaman, 'yeni yok')
    # Günlük 'hayattayım' mesajı (TR 10:00 sonrası ilk tarama): sessizlik = bozuk mu sorusu olmasın
    if datetime.now(TR).hour >= 10 and gor.get('_nabiz') != DAY:
        gor['_nabiz'] = DAY
        nabiz = f'✅ Sel radarı çalışıyor ({zaman}). Son 24 saatte {len([1 for k,v in gor.items() if not k.startswith("_") and v == DAY])} uyarı. Büyük olay olunca yazarım.'
        print(nabiz)
        if not DRY:
            gonder(nabiz)
    if hatalar:
        print('HATA:', hatalar)
    if not DRY:
        json.dump(gor, open(STATE, 'w'))

main()
