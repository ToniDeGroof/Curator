import streamlit as st
import streamlit.components.v1 as components
import json
import re
import io
import base64
import os
from datetime import datetime
from PIL import Image
from supabase import create_client, Client
from openai import OpenAI

# ReportLab bibliotheken voor PDF-generatie
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# ------------------------------------------
# CONFIGURATIE & PAGE SETUP
# ------------------------------------------
st.set_page_config(
    page_title="Fotografie Curator & Analyse Studio",
    page_icon="📷",
    layout="wide"
)

# Zorg dat alle lichtgrijze teksten in de app donkergrijs/zwart worden voor betere leesbaarheid
st.markdown("""
    <style>
    /* Maak alle st.caption en kleine hulpteksten donkergrijs */
    .stCaption, [data-testid="stCaptionContainer"] {
        color: #1A1A1A !important;
        font-weight: 500 !important;
    }
    /* Maak overige lichtgrijze subteksten en labels extra donker */
    small, .st-emotion-cache-16idsys, p {
        color: #111111 !important;
    }
    </style>
""", unsafe_allow_html=True)

st.markdown("""
<style>
    .badge-wow {
        background-color: #ff4b4b;
        color: white;
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 0.75rem;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)


# ------------------------------------------
# SUPABASE INITIALISATIE
# ------------------------------------------
@st.cache_resource
def init_supabase() -> Client:
    """Initialiseert de Supabase client via Streamlit secrets."""
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

try:
    supabase = init_supabase()
except Exception as e:
    supabase = None

def get_all_beoordelingen():
    """Haalt alle foto-beoordelingen op uit de Supabase database."""
    if not supabase:
        return []
    response = supabase.table("beoordelingen").select("*").order("created_at", desc=True).execute()
    return response.data

def delete_beoordeling(item_id):
    """Verwijder een specifieke beoordeling uit Supabase op basis van ID."""
    if not supabase:
        return False
    response = supabase.table("beoordelingen").delete().eq("id", item_id).execute()
    return response


# ------------------------------------------
# HELPER FUNCTIES
# ------------------------------------------
def parse_score(val):
    try:
        v = float(val)
        return v * 100 if v <= 1.0 else v
    except (ValueError, TypeError):
        return 0.0

def detect_formaat_from_image(pil_img):
    w, h = pil_img.size
    if w > h * 1.05:
        return "Liggend"
    elif h > w * 1.05:
        return "Staand"
    else:
        return "Vierkant"

def extract_profile_dict(item):
    raw_p = item.get("artistiek_profiel")
    if not raw_p:
        return {}
    if isinstance(raw_p, dict):
        return raw_p
    if isinstance(raw_p, str):
        try:
            res = json.loads(raw_p)
            return res if isinstance(res, dict) else {}
        except Exception:
            return {}
    return {}

def extract_genre(item):
    if item.get("genre"):
        return str(item.get("genre")).strip()
    p_dict = extract_profile_dict(item)
    meta = p_dict.get("meta_info", {})
    if isinstance(meta, dict) and meta.get("genre"):
        return str(meta.get("genre")).strip()
    return ""

def reset_curator_filters():
    st.session_state["curator_search_query"] = ""
    st.session_state["curator_module"] = "Alle modules"
    st.session_state["curator_genre"] = "Alle genres"
    st.session_state["curator_locatie"] = "Alle locaties"
    st.session_state["curator_datum"] = "Alle datums"
    st.session_state["curator_formaat"] = "Alle formaten"
    st.session_state["curator_kleurtype"] = "Alle kleurtypen"
    st.session_state["curator_min_score"] = 0
    st.session_state["curator_light_drama"] = 0
    st.session_state["curator_melancholy"] = 0
    st.session_state["curator_intimacy"] = 0
    st.session_state["curator_eyecatchers"] = False

# Hulpfunctie: EXIF data veilig uitlezen uit PIL Image
def extract_exif(image):
    exif_data = {}
    try:
        info = image._getexif()
        if info:
            for tag, value in info.items():
                decoded = TAGS.get(tag, tag)
                if isinstance(value, (bytes, str, int, float)):
                    exif_data[str(decoded)] = str(value)
    except Exception:
        pass
    return exif_data

# ------------------------------------------
# PDF GENERATOR FUNCTIE
# ------------------------------------------
def generate_pdf_report(titel, module, genre, locatie, datum, image_bytes, result_json):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    story = []

    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=18, leading=22, textColor=colors.HexColor("#1A1A1A"))
    h2_style = ParagraphStyle('H2Style', parent=styles['Heading2'], fontSize=13, leading=16, textColor=colors.HexColor("#2C3E50"), spaceBefore=10, spaceAfter=4)
    body_style = ParagraphStyle('BodyStyle', parent=styles['Normal'], fontSize=9, leading=12, textColor=colors.HexColor("#333333"))

    story.append(Paragraph(f"<b>CURATORIAAL EVALUATIERAPPORT</b>", title_style))
    story.append(Paragraph(f"<b>Werk:</b> {titel} | <b>Module:</b> {module} | <b>Genre:</b> {genre}", body_style))
    story.append(Paragraph(f"<b>Locatie:</b> {locatie} | <b>Datum:</b> {datum}", body_style))
    story.append(Spacer(1, 10))

    try:
        img_temp = io.BytesIO(image_bytes)
        rl_img = RLImage(img_temp, width=240, height=180)
        rl_img.hAlign = 'LEFT'
        story.append(rl_img)
    except Exception:
        pass

    story.append(Spacer(1, 10))

    # Totaalscore berekenen uit deelscores indien aanwezig
    deel = result_json.get("deelscores", {})
    totaal_score = sum(deel.values()) if deel else result_json.get("totaal_score", 0)
    jury_tekst = result_json.get("jurytekst", "Geen jurytekst beschikbaar.")

    story.append(Paragraph(f"<b>Totaalscore: {totaal_score}/100</b>", h2_style))
    
    # Formatteer de jurytekst (Markdown regeleindes omzetten voor ReportLab)
    formatted_tekst = jury_tekst.replace("\n", "<br/>")
    story.append(Paragraph(formatted_tekst, body_style))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

# ------------------------------------------
# HOOFDNAVIGATIE (3 TABS - GEEN EMOJI'S)
# ------------------------------------------
tab1, tab2, tab3 = st.tabs(["Foto Studio", "Selectie Studio", "Curator Studio"])

# ==========================================
# TAB 1: FOTO STUDIO (Beurtrol & Reeks)
# ==========================================
with tab1:
    st.title("Foto Studio")

    # INFO-VELD MET RICHTLIJNEN EN EISEN
    with st.expander("Voorwaarden & Eisen voor upload", expanded=False):
        st.markdown("""
        **Richtlijnen voor de beste analyse:**
        * **Bestandstypen:** JPG, JPEG, PNG of WEBP
        * **Bestandsgrootte:** Maximaal 10 MB per foto
        * **Aantal beelden:** Maximaal 20 foto's per upload-sessie
        * **Kwaliteit & Resolutie:** Aanbevolen minimaal 1080p aan de kortste zijde voor een nauwkeurige beoordeling van compositie en detail
        * **Kleurruimte:** sRGB heeft de voorkeur voor een getrouwe weergave van licht en kleur
        """)

    # Initialiseer session_state variabelen voor de beurtrol & sticky gegevens
    if "current_index" not in st.session_state:
        st.session_state.current_index = 0
    if "uploader_key" not in st.session_state:
        st.session_state.uploader_key = 0
    if "analysis_result" not in st.session_state:
        st.session_state.analysis_result = None

    # Sticky extra informatie (onthouden tussen foto's)
    if "last_module" not in st.session_state:
        st.session_state.last_module = "Module 1"
    if "last_genre" not in st.session_state:
        st.session_state.last_genre = "Straatfotografie"
    if "last_datumcode" not in st.session_state:
        st.session_state.last_datumcode = datetime.now().strftime("%Y%m")
    if "last_locatie" not in st.session_state:
        st.session_state.last_locatie = "Antwerpen, Belgie"
    if "last_kleurtype" not in st.session_state:
        st.session_state.last_kleurtype = "Kleur"
    if "last_intentie" not in st.session_state:
        st.session_state.last_intentie = ""

    uploaded_files = st.file_uploader(
        "Kies of sleep hier je foto's",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
        key=f"uploader_{st.session_state.uploader_key}"
    )

    if uploaded_files:
        total_files = len(uploaded_files)

        if st.session_state.current_index >= total_files:
            st.success(f"Alle {total_files} foto's uit deze reeks zijn verwerkt!")
            col_reset1, col_reset2 = st.columns([1, 1])
            with col_reset1:
                if st.button("Nieuwe selectie maken", type="primary", use_container_width=True):
                    st.session_state.current_index = 0
                    st.session_state.analysis_result = None
                    st.session_state.uploader_key += 1
                    st.rerun()
            with col_reset2:
                if st.button("Terug naar Startscherm", use_container_width=True):
                    st.session_state.current_index = 0
                    st.session_state.analysis_result = None
                    st.session_state.uploader_key += 1
                    st.rerun()
        else:
            current_file = uploaded_files[st.session_state.current_index]
            st.info(f"📸 Foto {st.session_state.current_index + 1} van {total_files}: **{current_file.name}**")

            col_preview, col_inputs = st.columns([0.38, 0.62], gap="large")

            # Afbeelding inlezen & Formaat berekenen
            file_bytes = current_file.read()
            image = Image.open(io.BytesIO(file_bytes))
            w, h = image.size
            aspect_ratio = w / h if h > 0 else 1.0
            berekend_formaat = detect_formaat_from_image(image)

            with col_preview:
                st.image(image, caption=f"{current_file.name} ({w}x{h} px)", use_container_width=True)
                st.info(f"Berekend Formaat: **{berekend_formaat}** (verhouding {aspect_ratio:.2f})")

            with col_inputs:
                st.markdown("#### Extra informatie")

                # Titel (standaard bestandsnaam zonder extensie)
                titel_default = os.path.splitext(current_file.name)[0]
                titel_in = st.text_input("Titel van het werk", value=titel_default)

                col_f1, col_f2 = st.columns(2)
                with col_f1:
                    module_in = st.text_input("Module", value=st.session_state.last_module)
                    datum_in = st.text_input("Datumcode (YYYYMM)", value=st.session_state.last_datumcode)

                    genre_lijst = ["Straatfotografie", "Portret", "Landschap", "Documentair", "Architectuur", "Stilleven", "Abstract", "Overig"]
                    genre_index = genre_lijst.index(st.session_state.last_genre) if st.session_state.last_genre in genre_lijst else 0
                    genre_in = st.selectbox("Genre", genre_lijst, index=genre_index)

                with col_f2:
                    locatie_in = st.text_input("Locatie", value=st.session_state.last_locatie)

                    kleur_lijst = ["Kleur", "Zwart-wit", "Monochroom"]
                    kleur_index = kleur_lijst.index(st.session_state.last_kleurtype) if st.session_state.last_kleurtype in kleur_lijst else 0
                    kleurtype_in = st.selectbox("Kleurtype", kleur_lijst, index=kleur_index)

                # Waarden direct opslaan in session_state (sticky gedrag)
                st.session_state.last_module = module_in
                st.session_state.last_datumcode = datum_in
                st.session_state.last_genre = genre_in
                st.session_state.last_locatie = locatie_in
                st.session_state.last_kleurtype = kleurtype_in

                intentie_in = st.text_area(
                    "Intentie van de fotograaf (optioneel)",
                    value=st.session_state.last_intentie,
                    placeholder="Wat wou je tonen of overbrengen?",
                    height=90
                )
                st.session_state.last_intentie = intentie_in

                # COMPACTE KNOPPEN DIRECT ONDER DE RECHTER VELDEN
                if st.session_state.analysis_result is None:
                    st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
                    btn_col1, btn_col2 = st.columns([1, 1])

                    with btn_col1:
                        if st.button(f"Start Analyse ({st.session_state.current_index + 1}/{total_files})", type="primary", use_container_width=True):
                            if "OPENAI_API_KEY" not in st.secrets:
                                st.error("OpenAI API key (OPENAI_API_KEY) ontbreekt in Streamlit secrets!")
                            else:
                                with st.spinner(f"Beoordeling & Profiel genereren voor '{titel_in}'..."):
                                    try:
                                        client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
                                        base64_image = base64.b64encode(file_bytes).decode('utf-8')
                                        str_intentie = intentie_in.strip() if intentie_in.strip() else "Niet opgegeven door de fotograaf."

                                        superprompt = f"""
Persona: Je bent een ervaren, analytische en veeleisende fotorecensent en curator aan een academie voor beeldende kunst. Beoordeel het beeld volgens onderstaande criteria én stel een uitgebreid multi-laags profiel op voor latere curatoriale analyse.

Context van de foto:
- Titel: {titel_in}
- Locatie: {locatie_in}
- Module: {module_in}
- Kleurtype: {kleurtype_in}
- Formaat: {berekend_formaat} (verhouding {aspect_ratio:.2f})
- Intentie: {str_intentie}

RUBRIC (Totaal exact 100 punten):
1. Verhaal & emotionele impact — max 30
2. Onderwerp & intentie — max 20
3. Originaliteit & experiment — max 15
4. Compositie & kadrering — max 15
5. Licht & kleur — max 10
6. Techniek — max 10

STRUCTUUR VAN DE JURYTEKST (Volg EXACT dit format):

**1. Analyse per criterium**

**Verhaal & emotionele impact**
<korte duidelijke analyse>
Score: <score>/30

**Onderwerp & intentie**
<korte duidelijke analyse>
Score: <score>/20

**Originaliteit & experiment**
<korte duidelijke analyse>
Score: <score>/15

**Compositie & kadrering**
<korte duidelijke analyse>
Score: <score>/15

**Licht & kleur**
<korte duidelijke analyse>
Score: <score>/10

**Techniek**
<korte duidelijke analyse>
Score: <score>/10

**2. Sterke punten**
• <punt 1>
• <punt 2>

**3. Zwakke punten**
• <punt 1>
• <punt 2>

**4. Verbeterpunten**
• <concreet verbeterpunt 1>
• <concreet verbeterpunt 2>

**5. Score-overzicht en motivatie**
<korte samenvattende motivatie>
Totaalscore: <berekende_som>/100

PROFIELERINGS-RICHTLIJNEN (Schalen van 0.0 tot 1.0):
- Maak onderscheid tussen wat zichtbaar is, wat plausibel gesuggereerd wordt en wat speculatie zou zijn. Schrijf geen intenties toe tenzij gegeven.

Antwoord uitsluitend in valide JSON met exact deze structuur:
{{
    "deelscores": {{
        "verhaal_emotie": <max 30>,
        "onderwerp_intentie": <max 20>,
        "originaliteit": <max 15>,
        "compositie": <max 15>,
        "licht_kleur": <max 10>,
        "techniek": <max 10>
    }},
    "formal_profile": {{
        "figuration_abstraction": <0.0=puur figuratief, 1.0=puur abstract>,
        "visual_complexity": <0.0=eenvoudig, 1.0=complex>,
        "symmetry": <0.0=asymmetrisch, 1.0=symmetrisch>,
        "spatial_depth": <0.0=vlak, 1.0=diep>,
        "movement": <0.0=statisch, 1.0=dynamisch>,
        "contrast": <0.0=laag, 1.0=hoog>,
        "color_intensity": <0.0=subtiel/monochroom, 1.0=verzadigd>,
        "light_drama": <0.0=vlak licht, 1.0=dramatisch/chiaroscuro>
    }},
    "emotional_profile": {{
        "intimacy": <0.0-1.0>,
        "tension": <0.0-1.0>,
        "melancholy": <0.0-1.0>,
        "serenity": <0.0-1.0>,
        "alienation": <0.0-1.0>,
        "vulnerability": <0.0-1.0>,
        "mystery": <0.0-1.0>,
        "dominant_tones": ["<term1>", "<term2>", "<term3>"]
    }},
    "conceptual_profile": {{
        "narrative_openness": <0.0=gesloten/expliciet, 1.0=open/mysterieus>,
        "symbolic_density": <0.0-1.0>,
        "documentary_poetic": <0.0=puur documentair, 1.0=poëtisch/suggestief>,
        "ambiguity": <0.0-1.0>
    }},
    "artistic_identity": {{
        "primary_character": "<korte samenvattende typeringszin>",
        "visual_voice": "<typering visuele stijl>",
        "distinctive_features": ["<kenmerk 1>", "<kenmerk 2>"]
    }},
    "curatorial_profile": {{
        "exhibition_role": "<bijv. rustpunt, openingsbeeld, contrast-element>",
        "ideal_context": "<korte beschrijving ideale tentoonstellingscontext>",
        "pair_suggestions": "<type beelden waarmee dit goed integreert>"
    }},
    "meta_info": {{
        "kleurtype": "{kleurtype_in}",
        "formaat": "{berekend_formaat}"
    }},
    "jurytekst": "**1. Analyse per criterium**\\n..."
}}
"""

                                        response = client.chat.completions.create(
                                            model="gpt-4o",
                                            response_format={"type": "json_object"},
                                            messages=[
                                                {
                                                    "role": "user",
                                                    "content": [
                                                        {"type": "text", "text": superprompt},
                                                        {
                                                            "type": "image_url",
                                                            "image_url": {
                                                                "url": f"data:image/jpeg;base64,{base64_image}"
                                                            }
                                                        }
                                                    ]
                                                }
                                            ]
                                        )

                                        result_data = json.loads(response.choices[0].message.content)
                                        deel = result_data.get("deelscores", {})
                                        calculated_total = sum(deel.values()) if deel else 0

                                        st.session_state.analysis_result = {
                                            "result_data": result_data,
                                            "calculated_total": calculated_total,
                                            "file_bytes": file_bytes,
                                            "titel": titel_in,
                                            "module": module_in,
                                            "genre": genre_in,
                                            "locatie": locatie_in,
                                            "datum": datum_in,
                                            "kleurtype": kleurtype_in,
                                            "formaat": berekend_formaat,
                                            "width": w,
                                            "height": h,
                                            "filename": current_file.name
                                        }
                                        st.rerun()

                                    except Exception as ex:
                                        st.error(f"Fout tijdens OpenAI analyse: {ex}")

                    with btn_col2:
                        if st.button("Terug naar Startscherm", use_container_width=True):
                            st.session_state.current_index = 0
                            st.session_state.analysis_result = None
                            st.session_state.uploader_key += 1
                            st.rerun()

            # ------------------------------------------
            # STAP 2: RESULTAAT TONEN & ACTIES (OPSLAAN / PDF / VOLGENDE)
            # ------------------------------------------
            if st.session_state.analysis_result is not None:
                st.markdown("---")
                ar = st.session_state.analysis_result
                res = ar["result_data"]
                total_score = ar["calculated_total"]

                st.markdown(f"### Evaluatieresultaat: **{ar['titel']}**")

                col_res1, col_res2 = st.columns([0.35, 0.65])

                with col_res1:
                    st.metric("Totaalscore", f"{total_score}/100")

                    deel = res.get("deelscores", {})
                    if deel:
                        st.markdown("**Deelscores Rubric:**")
                        st.write(f"- Verhaal & emotie: **{deel.get('verhaal_emotie', 0)}/30**")
                        st.write(f"- Onderwerp & intentie: **{deel.get('onderwerp_intentie', 0)}/20**")
                        st.write(f"- Originaliteit & exp.: **{deel.get('originaliteit', 0)}/15**")
                        st.write(f"- Compositie & kadrering: **{deel.get('compositie', 0)}/15**")
                        st.write(f"- Licht & kleur: **{deel.get('licht_kleur', 0)}/10**")
                        st.write(f"- Techniek: **{deel.get('techniek', 0)}/10**")

                with col_res2:
                    st.markdown("**Juryverslag:**")
                    st.markdown(res.get("jurytekst", ""))

                st.markdown("---")

                # Actieknoppen op 4 kolommen
                c1, c2, c3, c4 = st.columns(4)

                with c1:
                    if st.button("Opslaan in Database", type="primary", use_container_width=True):
                        with st.spinner("Opslaan in Supabase database en storage..."):
                            image_url = ""
                            if supabase:
                                try:
                                    storage_filename = f"{int(datetime.now().timestamp())}_{ar['filename']}"
                                    supabase.storage.from_("fotos").upload(storage_filename, ar["file_bytes"], {"content-type": "image/jpeg"})
                                    image_url = supabase.storage.from_("fotos").get_public_url(storage_filename)
                                except Exception as st_err:
                                    st.warning("Afbeelding kon niet geüpload worden naar Storage.")

                                record = {
                                    "titel": ar["titel"],
                                    "module": ar["module"],
                                    "genre": ar["genre"],
                                    "locatie": ar["locatie"],
                                    "datumcode": ar["datum"],
                                    "formaat": ar["formaat"].lower(),
                                    "kleurtype": ar["kleurtype"],
                                    "totaal_score": ar["calculated_total"],
                                    "jurytekst": res.get("jurytekst", ""),
                                    "artistiek_profiel": json.dumps(res),
                                    "image_url": image_url,
                                    "width": ar["width"],
                                    "height": ar["height"]
                                }
                                try:
                                    supabase.table("beoordelingen").insert(record).execute()
                                    st.success("Succesvol opgeslagen in Supabase!")
                                except Exception as db_err:
                                    st.error(f"Fout bij opslaan in database: {db_err}")

                with c2:
                    pdf_data = generate_pdf_report(ar['titel'], ar['module'], ar['genre'], ar['locatie'], ar['datum'], ar['file_bytes'], res)
                    st.download_button(
                        label="PDF Genereren",
                        data=pdf_data,
                        file_name=f"Analyse_{ar['titel']}.pdf",
                        mime="application/pdf",
                        use_container_width=True
                    )

                with c3:
                    if st.button("Volgende beoordelen", use_container_width=True):
                        st.session_state.analysis_result = None
                        st.session_state.last_intentie = ""  # Reset intentie voor de volgende foto
                        st.session_state.current_index += 1
                        st.rerun()

                with c4:
                    if st.button("Terug naar Startscherm", use_container_width=True):
                        st.session_state.current_index = 0
                        st.session_state.analysis_result = None
                        st.session_state.uploader_key += 1
                        st.rerun()

# ------------------------------------------
# TAB 2: CURATOR MODULE & ARCHIEF
# ------------------------------------------
with tab2:
    import json
    import re

    # CSS OM DE PIJLTJES VAN ST.EXPANDER EN ST.POPOVER TE VERBERGEN EN DE TEKST TE CENTREREN
    st.markdown("""
    <style>
        /* 1. EXPANDER HEADER FIX */
        [data-testid="stExpander"] details summary svg {
            display: none !important;
        }
        [data-testid="stExpander"] details summary {
            justify-content: center !important;
            text-align: center !important;
        }
        [data-testid="stExpander"] details summary div,
        [data-testid="stExpander"] details summary p {
            justify-content: center !important;
            text-align: center !important;
            width: 100% !important;
            margin: 0 auto !important;
        }

        /* 2. POPOVER BUTTON FIX */
        [data-testid="stPopover"] button svg {
            display: none !important;
        }
        [data-testid="stPopover"] button p {
            width: 100% !important;
            text-align: center !important;
            margin: 0 auto !important;
        }
    </style>
    """, unsafe_allow_html=True)

    st.subheader("Curatoriale Collectie-Analyse & Selectie")

    # 1. INITIALISEER DE UITSLUITLIJST EN WERKSET IN SESSION STATE
    if "excluded_curator_ids" not in st.session_state:
        st.session_state.excluded_curator_ids = set()
    
    if "curator_basket" not in st.session_state:
        st.session_state.curator_basket = {}  # Dictionary {item_id: item_dict}

    try:
        # Haal beelden op via de bestaande functie of Supabase
        if "get_all_beoordelingen" in globals():
            all_items = get_all_beoordelingen()
        elif "fetch_beoordelingen" in globals():
            all_items = fetch_beoordelingen()
        elif "supabase" in globals() and supabase:
            res = supabase.table("beoordelingen").select("*").execute()
            all_items = res.data if res and hasattr(res, 'data') else []
        else:
            all_items = []

        if not all_items:
            st.warning("Er staan nog geen foto's in het archief om te cureren.")
        else:
            # WERKSET STATUSBALK (BOVENAAN)
            basket_count = len(st.session_state.curator_basket)
            with st.container(border=True):
                col_b1, col_b2, col_b3 = st.columns([0.6, 0.2, 0.2])
                with col_b1:
                    st.markdown(f"🛒 **Actieve Werkset voor Studio's:** `{basket_count}` foto('s) verzameld")
                with col_b2:
                    if st.button("🗑️ Werkset leegmaken", use_container_width=True, disabled=(basket_count == 0)):
                        st.session_state.curator_basket.clear()
                        st.rerun()
                with col_b3:
                    if st.button("🚀 Naar Studio (Tab 3)", type="primary", use_container_width=True, disabled=(basket_count == 0)):
                        st.info("Werkset is overgedragen aan Studio!")

            st.markdown("---")

            # DYNAMIC DROPDOWN OPTIES OPHALEN
            existing_modules = ["Alle modules"] + sorted(list(set([item.get("module") for item in all_items if item.get("module")])))
            existing_locations = ["Alle locaties"] + sorted(list(set([item.get("locatie") for item in all_items if item.get("locatie")])))
            existing_dates = ["Alle datums"] + sorted(list(set([item.get("datumcode") for item in all_items if item.get("datumcode")])))
            existing_genres = ["Alle genres"] + sorted(list(set([item.get("genre") for item in all_items if item.get("genre")])))

            # ACTIEKNOPPEN EN ZOEKBALK BOVENAAN
            c_top_1, c_top_2, c_top_3, c_top_4 = st.columns([0.45, 0.18, 0.18, 0.19])
            
            with c_top_1:
                search_query = st.text_input(
                    "Slim zoeken / Zoekopdracht", 
                    key="curator_search_query",
                    placeholder="Bijv. '5 beste kleurfoto's', '10 foto's met veel melancholie'..."
                ).lower().strip()

            with c_top_2:
                st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
                apply_filters = st.button("Voer selectie uit", type="primary", use_container_width=True)

            with c_top_3:
                st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
                if "reset_curator_filters" in globals():
                    st.button("Reset filters", use_container_width=True, on_click=reset_curator_filters)
                else:
                    if st.button("Reset filters", use_container_width=True):
                        st.session_state.curator_search_query = ""
                        st.rerun()

            with c_top_4:
                st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
                num_excluded = len(st.session_state.excluded_curator_ids)
                if st.button(f"Herstel verborgen ({num_excluded})", use_container_width=True, disabled=(num_excluded == 0)):
                    st.session_state.excluded_curator_ids.clear()
                    st.rerun()

            # ZOEKBALK ANALYSE (NLP / INTENTIE DETECTIE)
            top_n_requested = None
            top_n_match = re.search(r'(\d+)\s*(beste|hoogste|top|foto|beeld|foto\'s|beelden)|top\s*(\d+)', search_query)
            if top_n_match:
                top_n_requested = int(top_n_match.group(1) or top_n_match.group(3))

            search_kleur = None
            if "zwart-wit" in search_query or "zwart wit" in search_query or "monochroom" in search_query:
                search_kleur = "zwart-wit"
            elif "kleur" in search_query and "zwart" not in search_query:
                search_kleur = "kleur"

            search_melancholy = ("melancholie" in search_query or "melancholisch" in search_query)
            search_drama = ("drama" in search_query or "dramatisch" in search_query or "licht" in search_query)

            # UITGEBREID FILTERPANEEL
            with st.expander("Uitgebreide Filters & Kenmerken", expanded=True):
                c_f1, c_f2, c_f3, c_f4 = st.columns(4)
                
                with c_f1:
                    sel_module = st.selectbox("Module", existing_modules, key="curator_module")
                    sel_genre = st.selectbox("Genre", existing_genres, key="curator_genre")
                    sel_locatie = st.selectbox("Locatie", existing_locations, key="curator_locatie")

                with c_f2:
                    sel_datum = st.selectbox("Datumcode (YYYYMM)", existing_dates, key="curator_datum")
                    sel_formaat = st.selectbox("Formaat", ["Alle formaten", "Staand", "Liggend", "Vierkant"], key="curator_formaat")
                    sel_kleurtype = st.selectbox("Kleurtype", ["Alle kleurtypen", "Kleur", "Zwart-wit", "Monochroom"], key="curator_kleurtype")

                with c_f3:
                    min_score = st.slider("Minimale Eindscore", 0, 100, key="curator_min_score")
                    min_light_drama = st.slider("Min. Licht-dramatiek", 0, 100, key="curator_light_drama")
                    only_eyecatchers = st.checkbox("Alleen Eyecatchers", key="curator_eyecatchers")

                with c_f4:
                    min_melancholy = st.slider("Min. Melancholie-score", 0, 100, key="curator_melancholy")
                    min_intimacy = st.slider("Min. Intimiteit-score", 0, 100, key="curator_intimacy")

            # FILTERLOGICA
            filtered_items = []
            
            for item in all_items:
                item_id = item.get("id")

                # SLA HANDMATIG VERBORGEN BEELDEN OVER
                if item_id in st.session_state.excluded_curator_ids:
                    continue

                raw_p = item.get("artistiek_profiel")
                p_dict = {}
                if raw_p:
                    try:
                        p_dict = json.loads(raw_p) if isinstance(raw_p, str) else raw_p
                    except Exception:
                        pass

                formal = p_dict.get("formal_profile", {})
                emotional = p_dict.get("emotional_profile", {})
                artistic = p_dict.get("artistic_identity", {})
                curatorial = p_dict.get("curatorial_profile", {})
                meta_info = p_dict.get("meta_info", {})

                item_kleurtype = str(meta_info.get("kleurtype") or item.get("kleurtype") or p_dict.get("kleurtype") or "").strip().lower()
                item_formaat = str(meta_info.get("formaat") or item.get("formaat") or p_dict.get("formaat") or "").strip().lower()

                if sel_genre != "Alle genres" and item.get("genre") != sel_genre:
                    continue
                if sel_kleurtype != "Alle kleurtypen" and sel_kleurtype.lower() not in item_kleurtype:
                    continue
                if sel_formaat != "Alle formaten" and sel_formaat.lower() not in item_formaat:
                    continue
                if search_kleur and search_kleur not in item_kleurtype:
                    continue

                if sel_module != "Alle modules" and item.get("module") != sel_module:
                    continue
                if sel_locatie != "Alle locaties" and item.get("locatie") != sel_locatie:
                    continue
                if sel_datum != "Alle datums" and item.get("datumcode") != sel_datum:
                    continue

                item_score = item.get("totaal_score") or item.get("score") or 0
                if item_score < min_score:
                    continue

                def parse_score(val):
                    try:
                        v = float(val)
                        return v * 100 if v <= 1.0 else v
                    except (ValueError, TypeError):
                        return 0.0

                light_drama_val = parse_score(formal.get("light_drama", 0))
                melancholy_val = parse_score(emotional.get("melancholy", 0))
                intimacy_val = parse_score(emotional.get("intimacy", 0))

                if search_melancholy and melancholy_val < 45:
                    continue
                if search_drama and light_drama_val < 45:
                    continue

                if light_drama_val < min_light_drama or melancholy_val < min_melancholy or intimacy_val < min_intimacy:
                    continue

                # EYECATCHER LOGICA: STRIKT HOGER DAN 85
                is_eyecatcher = (item_score > 85) or (light_drama_val >= 80) or ("openingsbeeld" in str(curatorial.get("exhibition_role", "")).lower())
                if only_eyecatchers and not is_eyecatcher:
                    continue

                stopwords = {"alle", "geef", "de", "het", "een", "met", "veel", "foto", "foto's", "beeld", "beelden", "beste", "top", "voor", "van", "uit", "kleur", "kleurfoto's", "zwart-wit", "melancholie", "intimiteit"}
                clean_words = [w for w in re.findall(r'\w+', search_query) if len(w) > 2 and w not in stopwords]

                if clean_words and not top_n_requested:
                    text_to_search = f"{item.get('titel', '')} {item.get('module', '')} {item.get('genre', '')} {item.get('locatie', '')} {item.get('datumcode', '')} {item.get('jurytekst', '')} {artistic.get('primary_character', '')} {artistic.get('visual_voice', '')} {' '.join(emotional.get('dominant_tones', []))}".lower()
                    if not any(w in text_to_search for w in clean_words):
                        continue

                filtered_items.append((item, p_dict, is_eyecatcher))

            filtered_items.sort(key=lambda x: x[0].get("totaal_score") or x[0].get("score") or 0, reverse=True)

            if top_n_requested and top_n_requested > 0:
                filtered_items = filtered_items[:top_n_requested]
                st.info(f"Zoekopdracht verwerkt: {len(filtered_items)} beelden geselecteerd.")

            st.markdown("---")
            
            # HEAD-LINE + BATCH TOEVOEGEN AAN WERKSET
            c_res_head, c_res_btn = st.columns([0.65, 0.35])
            with c_res_head:
                st.markdown(f"### Selectie: **{len(filtered_items)}** van **{len(all_items)}** beelden")
            with c_res_btn:
                if filtered_items:
                    if st.button("➕ Voeg álle getoonde resultaten toe", use_container_width=True):
                        for item_tuple in filtered_items:
                            itm = item_tuple[0]
                            st.session_state.curator_basket[itm.get("id")] = itm
                        st.success(f"{len(filtered_items)} foto's toegevoegd aan werkset!")
                        st.rerun()

            if not filtered_items:
                st.info("Geen beelden gevonden die voldoen aan alle gekozen criteria. Klik op 'Reset filters' om opnieuw te beginnen.")
            else:
                cols_per_row = 8
                
                for i in range(0, len(filtered_items), cols_per_row):
                    row_batch = filtered_items[i:i + cols_per_row]
                    cols = st.columns(cols_per_row)
                    
                    for idx, (item, p_dict, is_eyecatcher) in enumerate(row_batch):
                        item_id = item.get("id")
                        
                        formal = p_dict.get("formal_profile", {})
                        emotional = p_dict.get("emotional_profile", {})
                        
                        raw_deel = item.get("deelscores") or p_dict.get("deelscores") or {}
                        if isinstance(raw_deel, str):
                            try:
                                deel = json.loads(raw_deel)
                            except Exception:
                                deel = {}
                        elif isinstance(raw_deel, dict):
                            deel = raw_deel
                        else:
                            deel = {}

                        s_verhaal = deel.get('verhaal_emotie', item.get('score_verhaal', 0))
                        s_onderwerp = deel.get('onderwerp_intentie', item.get('score_onderwerp', 0))
                        s_originaliteit = deel.get('originaliteit', item.get('score_originaliteit', 0))
                        s_compositie = deel.get('compositie', item.get('score_compositie', 0))
                        s_licht = deel.get('licht_kleur', item.get('score_licht', 0))
                        s_techniek = deel.get('techniek', item.get('score_techniek', 0))

                        with cols[idx]:
                            with st.container(border=True):
                                if item.get("image_url"):
                                    st.image(item.get("image_url"), use_container_width=True)
                                
                                if is_eyecatcher:
                                    st.markdown("<p style='color:#111; font-weight:bold; font-size:11px; margin:0;'>Eyecatcher</p>", unsafe_allow_html=True)
                                
                                st.markdown(f"<p style='color:#000; font-weight:bold; font-size:12px; margin-top:2px; margin-bottom:2px;'>{item.get('titel', 'Naamloos')}</p>", unsafe_allow_html=True)
                                
                                score_display = item.get("totaal_score") or item.get("score") or "N/B"
                                st.markdown(f"<p style='color:#111; font-size:12px; margin-bottom:4px;'>Score: <b>{score_display}</b>/100</p>", unsafe_allow_html=True)

                                # STATUS INDICATOR VOOR DE WERKSET
                                is_in_basket = item_id in st.session_state.curator_basket
                                if is_in_basket:
                                    st.markdown("<p style='color:#2e7d32; font-size:11px; font-weight:bold; margin-bottom:4px;'>✅ In werkset</p>", unsafe_allow_html=True)

                                # EÉN CENTRALE KNOP DIE HET BEHEERMENU OPENT
                                with st.popover("⚙️ Beheer foto", use_container_width=True):
                                    st.markdown(f"**{item.get('titel', 'Naamloos')}**")
                                    
                                    # 1. WERKSET TOEVOEGEN / VERWIJDEREN
                                    if is_in_basket:
                                        if st.button("➖ Verwijder uit werkset", key=f"btn_basket_rem_{item_id}", use_container_width=True):
                                            st.session_state.curator_basket.pop(item_id, None)
                                            st.rerun()
                                    else:
                                        if st.button("➕ Voeg toe aan werkset", key=f"btn_basket_add_{item_id}", use_container_width=True, type="primary"):
                                            st.session_state.curator_basket[item_id] = item
                                            st.rerun()

                                    st.markdown("---")

                                    # 2. TOON DEELSCORES & PROFIEL
                                    with st.expander("📊 Bekijk deelscores & profiel", expanded=False):
                                        st.markdown(f"- Verhaal & emotie: **{s_verhaal}/30**")
                                        st.markdown(f"- Onderwerp & intentie: **{s_onderwerp}/20**")
                                        st.markdown(f"- Originaliteit: **{s_originaliteit}/15**")
                                        st.markdown(f"- Compositie: **{s_compositie}/15**")
                                        st.markdown(f"- Licht & kleur: **{s_licht}/10**")
                                        st.markdown(f"- Techniek: **{s_techniek}/10**")
                                        
                                        st.markdown("---")
                                        
                                        def get_score_num(val):
                                            try:
                                                v = float(val)
                                                return int(round(v * 100 if v <= 1.0 else v))
                                            except (ValueError, TypeError):
                                                return 0

                                        ld_score = get_score_num(formal.get("light_drama", 0))
                                        mel_score = get_score_num(emotional.get("melancholy", 0))
                                        int_score = get_score_num(emotional.get("intimacy", 0))

                                        st.caption(f"Licht-dramatiek: {ld_score}/100")
                                        st.progress(ld_score / 100.0)

                                        st.caption(f"Melancholie: {mel_score}/100")
                                        st.progress(mel_score / 100.0)

                                        st.caption(f"Intimiteit: {int_score}/100")
                                        st.progress(int_score / 100.0)

                                    st.markdown("---")

                                    # 3. VERBERGEN IN SELECTIE
                                    if st.button("👁️ Verberg in deze weergave", key=f"hide_cur_{item_id}", use_container_width=True):
                                        st.session_state.excluded_curator_ids.add(item_id)
                                        st.rerun()

                                    # 4. DEFINITIEF VERWIJDEREN
                                    with st.expander("🗑️ Wis uit database"):
                                        st.warning("Dit wist de foto definitief!")
                                        bevestig = st.checkbox("Bevestig", key=f"confirm_cur_del_{item_id}")
                                        if st.button("Definitief wissen", key=f"del_cur_perm_{item_id}", disabled=not bevestig, type="primary", use_container_width=True):
                                            if "delete_beoordeling" in globals():
                                                delete_beoordeling(item_id)
                                                st.rerun()
                                            elif "supabase" in globals() and supabase:
                                                supabase.table("beoordelingen").delete().eq("id", item_id).execute()
                                                st.rerun()

    except Exception as e:
        st.error(f"Fout bij het laden van de Curator Module: {e}")

#====================================================================================#
# TAB 3 =============================================================================#
#====================================================================================#

with tab3:
    st.subheader("Curator Studio: AI-Gestuurde Expositie & Selectie")

    basket = st.session_state.get("curator_basket", {})
    basket_items = list(basket.values())

    if not basket_items:
        st.info("💡 Je werkset is nog leeg. Ga naar **Tab 2 (Selectie Studio)** en voeg beelden toe aan je werkset.")
    else:
        st.markdown(f"### 🎨 Werkset: **{len(basket_items)} beelden** geladen voor curatie")
        
        curator_tab1, curator_tab2 = st.tabs(["🤖 AI Curatie Wizard", "🖼️ Huidige Werkset Overzien"])

        # -------------------------------------------------------------
        # SUBTAB 2: Werkset Overzicht (Geen herhalingen meer)
        # -------------------------------------------------------------
        with curator_tab2:
            st.caption("Overzicht van alle beelden die momenteel in de werkset zitten.")
            cols_per_row = 6
            for i in range(0, len(basket_items), cols_per_row):
                row_batch = basket_items[i:i + cols_per_row]
                cols = st.columns(cols_per_row)
                for idx, item in enumerate(row_batch):
                    item_id = item.get("id")
                    with cols[idx]:
                        with st.container(border=True):
                            if item.get("image_url"):
                                st.image(item.get("image_url"), use_container_width=True)
                            st.markdown(f"**{item.get('titel', 'Naamloos')}**")
                            st.caption(f"📍 {item.get('locatie', 'N/B')} | Score: {item.get('totaal_score', 'N/B')}")
                            if st.button("❌ Wis", key=f"t3_grid_rem_{item_id}", use_container_width=True):
                                st.session_state.curator_basket.pop(item_id, None)
                                st.rerun()

        # -------------------------------------------------------------
        # SUBTAB 1: AI Curatie Wizard
        # -------------------------------------------------------------
        with curator_tab1:
            st.markdown("#### **Stap 1: Wat is het doel van deze selectie?**")
            
            doel = st.selectbox(
                "Kies de bestemming voor deze beelden:",
                [
                    "-- Selecteer een doel --",
                    "Tentoonstelling / Expositie",
                    "Fotoboek / Publicatie",
                    "Voor een Jury brengen / Evaluatie",
                    "Portfolio samenstellen",
                    "Fotowedstrijd inzending",
                    "Digitale Presentatie / Slideshow",
                    "Social Media Reeks"
                ],
                key="curator_doel"
            )

            if doel != "-- Selecteer een doel --":
                st.markdown("---")
                st.markdown(f"#### **Stap 2: Specificaties voor '{doel}'**")

                c_v1, c_v2 = st.columns(2)

                # Standaardwaarden om variabelen altijd te definiëren
                ritme = "N/B"
                formaat_voorkeur = "N/B"
                spread_type = "N/B"
                hoofdstukken = "N/B"
                jury_focus = "N/B"
                variatie = "N/B"
                portfolio_type = "N/B"
                volgorde_stijl = "N/B"
                focus_social = "N/B"

                if doel == "Tentoonstelling / Expositie":
                    with c_v1:
                        aantal_gewenst = st.number_input("Gewenst aantal beelden aan de wand:", min_value=1, max_value=len(basket_items), value=min(10, len(basket_items)))
                        lopending_meters = st.number_input("Beschikbare lopende meters muur:", min_value=1, value=15)
                    with c_v2:
                        ritme = st.selectbox("Welk visueel ritme zoek je?", ["Klassiek & Rustig", "Dynamisch & Variabel", "Minimalistisch (Veel witruimte)", "Chronologisch / Verhalend"])
                        formaat_voorkeur = st.selectbox("Voorkeur voor fysiek formaat:", ["Gemengde formaten", "Eén vast formaat", "Grote eyecatchers met kleine accenten"])

                elif doel == "Fotoboek / Publicatie":
                    with c_v1:
                        aantal_gewenst = st.number_input("Totaal aantal foto's in het boek:", min_value=1, max_value=len(basket_items), value=min(20, len(basket_items)))
                        spread_type = st.selectbox("Opbouw van de spreads:", ["1 foto per pagina + rustpagina's", "Duets / Tweeluiken die matchen", "Verhalende reeksen"])
                    with c_v2:
                        hoofdstukken = st.slider("Aantal hoofdstukken / secties:", 1, 5, 2)

                elif doel in ["Voor een Jury brengen / Evaluatie", "Fotowedstrijd inzending"]:
                    with c_v1:
                        aantal_gewenst = st.number_input("Maximaal toegestane inzendingen:", min_value=1, max_value=len(basket_items), value=min(5, len(basket_items)))
                        jury_focus = st.selectbox("Belangrijkste juriecriterium:", ["Hoogste technische & artistieke score", "Unieke verhaallijn / Concept", "Maximale visuele impact / Wauw-factor"])
                    with c_v2:
                        variatie = st.selectbox("Diversiteit in inzending:", ["Maximale diversiteit in stijlen", "Eén hele strakke, consistente serie"])

                elif doel == "Portfolio samenstellen":
                    with c_v1:
                        aantal_gewenst = st.number_input("Aantal portfolio beelden:", min_value=1, max_value=len(basket_items), value=min(12, len(basket_items)))
                        portfolio_type = st.selectbox("Focus van het portfolio:", ["Brede artistieke signatuur", "Specifiek landschap & sfeer", "Commercieel / Opdrachtgevers"])
                    with c_v2:
                        volgorde_stijl = st.selectbox("Volgorde opbouw:", ["Sterkste beelden eerst en laatst", "Sfeerovergang (Kleur -> Zwart/Wit)", "Thematisch"])

                else:
                    with c_v1:
                        aantal_gewenst = st.number_input("Aantal beelden in de reeks:", min_value=1, max_value=len(basket_items), value=min(7, len(basket_items)))
                    with c_v2:
                        focus_social = st.selectbox("Doel van de reeks:", ["Maximale stop-kracht (Eyecatchers)", "Verhalende carrousel", "Esthetische feed-harmonie"])

                st.markdown("---")
                st.markdown("#### **Stap 3: Dramaturgie & Sfeeropbouw**")
                
                c_s1, c_s2 = st.columns(2)
                with c_s1:
                    emotie_verloop = st.selectbox(
                        "Hoe moet de emotionele boog verlopen?",
                        [
                            "Vrij laten (AI bepaalt de beste harmonie)",
                            "Beginnen met rust/intimiteit -> Eindigen met drama/impact",
                            "Beginnen met eyecatcher -> Rustpunt in het midden -> Sterke finale",
                            "Consistent melancholisch & stil",
                            "Hoog contrast en dynamiek tussen opeenvolgende beelden"
                        ]
                    )
                with c_s2:
                    sturing_rustpunten = st.checkbox("Gebruik specifieke 'rustpunten' en 'openingsbeelden' uit de metadata", value=True)

                st.markdown("---")

                # KNOP OM DE CURATIE TE STARTEN
                if st.button("🚀 Start AI-Curatie & Genereer Selectie", key="tab3_start_curation", type="primary", use_container_width=True):
                    with st.spinner("AI-Curator analyseert de metadata, sfeerprofielen en opbouw van je werkset..."):
                        
                        # 1. Metadata verzamelen
                        items_summary = []
                        for idx, item in enumerate(basket_items):
                            raw_p = item.get("artistiek_profiel") or {}
                            if isinstance(raw_p, str):
                                try: raw_p = json.loads(raw_p) or {}
                                except: raw_p = {}
                            if not isinstance(raw_p, dict):
                                raw_p = {}

                            formal = raw_p.get("formal_profile") or {}
                            emotional = raw_p.get("emotional_profile") or {}
                            curatorial = raw_p.get("curatorial_profile") or {}
                            artistic_id = raw_p.get("artistic_identity") or {}

                            summary = {
                                "id": item.get("id"),
                                "titel": item.get("titel", "Naamloos"),
                                "locatie": item.get("locatie", "Onbekend"),
                                "score": item.get("totaal_score") or item.get("score") or 0,
                                "image_url": item.get("image_url", ""),
                                "light_drama": formal.get("light_drama", 0),
                                "melancholy": emotional.get("melancholy", 0),
                                "intimacy": emotional.get("intimacy", 0),
                                "exhibition_role": curatorial.get("exhibition_role", "Neutraal"),
                                "primary_character": artistic_id.get("primary_character", "")
                            }
                            items_summary.append(summary)

                        # 2. Prompts bouwen
                        system_prompt = """Je bent een gerespecteerde en ervaren hoofdcurator van een vooraanstaand museum voor hedendaagse fotografie.
Jouw taak is om uit een gegeven verzameling foto's de meest krachtige, coherente en dramaturgisch meeslepende selectie en volgorde samen te stellen voor een specifieke bestemming.
Geef je antwoord UITSLUITEND terug in geldig JSON-formaat zonder extra tekst."""

                        user_prompt = f"""
Gelieve een curatie uit te voeren met de onderstaande instellingen:

**CURATIE GOAL & CRITERIA:**
- Hoofddoel: {doel}
- Aantal te selecteren beelden: {aantal_gewenst}
- Gewenst emotioneel verloop: {emotie_verloop}
- Ritme: {ritme} | Formaatvoorkeur: {formaat_voorkeur}
- Jury focus: {jury_focus} | Portfolio type: {portfolio_type}
- Rekening houden met specifieke rustpunten: {sturing_rustpunten}

**BESCHIKBARE FOTO'S IN WERKSET:**
{json.dumps(items_summary, indent=2, ensure_ascii=False)}

**GEWENST OUTPUT JSON FORMAAT:**
{{
  "overall_concept": "Korte samenvatting van het curatorthema/devisie",
  "selected_items": [
    {{
      "id": "foto_id",
      "position": 1,
      "role_tag": "🚀 Startbeeld | 🌿 Rustpunt",
      "motivering": "Professionele curatorial motivering..."
    }}
  ]
}}
"""

                        # 3. LLM API Call
                        try:
                            response = client.chat.completions.create(
                                model="gpt-4o",
                                messages=[
                                    {"role": "system", "content": system_prompt},
                                    {"role": "user", "content": user_prompt}
                                ],
                                response_format={"type": "json_object"},
                                temperature=0.7
                            )
                            
                            ai_result = json.loads(response.choices[0].message.content)
                            
                            curated_list = []
                            for sel in ai_result.get("selected_items", []):
                                orig = next((x for x in items_summary if str(x["id"]) == str(sel["id"])), None)
                                if orig:
                                    item_combined = orig.copy()
                                    item_combined["position"] = sel.get("position")
                                    item_combined["role_tag"] = sel.get("role_tag", "🖼️ Wandbeeld")
                                    item_combined["ai_motivering"] = sel.get("motivering", "")
                                    curated_list.append(item_combined)
                            
                            curated_list.sort(key=lambda x: x.get("position", 99))
                            st.session_state["curated_selection"] = curated_list
                            st.session_state["curator_concept"] = ai_result.get("overall_concept", "")

                        except Exception as e:
                            st.error(f"Er is een fout opgetreden bij de AI-curatie: {e}")
                            sorted_items = sorted(items_summary, key=lambda x: x["score"], reverse=True)[:aantal_gewenst]
                            for idx, s in enumerate(sorted_items, 1):
                                s["position"] = idx
                                s["role_tag"] = "🖼️ Wandbeeld"
                                s["ai_motivering"] = f"Geselecteerd op basis van een hoge kwaliteitsscore ({s['score']}/100)."
                            st.session_state["curated_selection"] = sorted_items

                # -------------------------------------------------------------
                # TOON EXPOSITIEWAND & RAPPORT (INCLUSIEF BINNEN SUBTAB 1)
                # -------------------------------------------------------------
                if "curated_selection" in st.session_state and st.session_state["curated_selection"]:
                    sorted_items = st.session_state["curated_selection"]

                    st.markdown("---")
                    st.markdown("### 🏛️ Expositiewand (Interactieve Drag & Drop Strip)")
                    st.caption("🖐️ **Schuif de beelden met je muis naar links of rechts** om de gewenste volgorde aan de muur aan te passen!")

                    cards_html = ""
                    for idx, s_item in enumerate(sorted_items):
                        img_src = s_item.get("image_url", "")
                        cards_html += f"""
                        <div class="drag-card" draggable="true" data-id="{s_item['id']}">
                            <div class="card-num">#{s_item.get('position', idx + 1)}</div>
                            <div class="img-container">
                                <img src="{img_src}" alt="{s_item['titel']}" />
                            </div>
                            <div class="card-title">{s_item['titel']}</div>
                            <div class="card-sub">📍 {s_item['locatie']}</div>
                        </div>
                        """

                    drag_drop_script = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                    <style>
                        body {{
                            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                            margin: 0;
                            padding: 10px;
                            background-color: transparent;
                        }}
                        .wall-container {{
                            display: flex;
                            gap: 12px;
                            overflow-x: auto;
                            padding: 10px 5px 20px 5px;
                            scroll-behavior: smooth;
                        }}
                        .drag-card {{
                            flex: 0 0 160px;
                            background: #ffffff;
                            border: 1px solid #e0e0e0;
                            border-radius: 8px;
                            padding: 8px;
                            box-shadow: 0 2px 6px rgba(0,0,0,0.08);
                            cursor: grab;
                            transition: transform 0.2s, box-shadow 0.2s;
                            user-select: none;
                        }}
                        .drag-card:active {{
                            cursor: grabbing;
                            transform: scale(1.03);
                            box-shadow: 0 6px 14px rgba(0,0,0,0.15);
                        }}
                        .drag-card.dragging {{
                            opacity: 0.4;
                            border: 2px dashed #007bff;
                        }}
                        .card-num {{
                            font-size: 11px;
                            font-weight: bold;
                            color: #007bff;
                            margin-bottom: 4px;
                        }}
                        .img-container {{
                            width: 100%;
                            height: 120px;
                            background: #f8f9fa;
                            border-radius: 4px;
                            overflow: hidden;
                            display: flex;
                            align-items: center;
                            justify-content: center;
                        }}
                        .img-container img {{
                            width: 100%;
                            height: 100%;
                            object-fit: cover;
                            pointer-events: none;
                        }}
                        .card-title {{
                            font-size: 12px;
                            font-weight: 600;
                            color: #212529;
                            margin-top: 6px;
                            white-space: nowrap;
                            overflow: hidden;
                            text-overflow: ellipsis;
                        }}
                        .card-sub {{
                            font-size: 10px;
                            color: #6c757d;
                        }}
                    </style>
                    </head>
                    <body>

                    <div class="wall-container" id="wall">
                        {cards_html}
                    </div>

                    <script>
                        const container = document.getElementById('wall');
                        let draggedCard = null;

                        container.addEventListener('dragstart', (e) => {{
                            if (e.target.classList.contains('drag-card')) {{
                                draggedCard = e.target;
                                e.target.classList.add('dragging');
                            }}
                        }});

                        container.addEventListener('dragend', (e) => {{
                            if (e.target.classList.contains('drag-card')) {{
                                e.target.classList.remove('dragging');
                                updateCardNumbers();
                            }}
                        }});

                        container.addEventListener('dragover', (e) => {{
                            e.preventDefault();
                            const afterElement = getDragAfterElement(container, e.clientX);
                            if (afterElement == null) {{
                                container.appendChild(draggedCard);
                            }} else {{
                                container.insertBefore(draggedCard, afterElement);
                            }}
                        }});

                        function getDragAfterElement(container, x) {{
                            const draggableElements = [...container.querySelectorAll('.drag-card:not(.dragging)')];
                            return draggableElements.reduce((closest, child) => {{
                                const box = child.getBoundingClientRect();
                                const offset = x - box.left - box.width / 2;
                                if (offset < 0 && offset > closest.offset) {{
                                    return {{ offset: offset, element: child }};
                                }} else {{
                                    return closest;
                                }}
                            }}, {{ offset: Number.NEGATIVE_INFINITY }}).element;
                        }}

                        function updateCardNumbers() {{
                            const cards = container.querySelectorAll('.drag-card');
                            cards.forEach((card, index) => {{
                                card.querySelector('.card-num').textContent = '#' + (index + 1);
                            }});
                        }}
                    </script>
                    </body>
                    </html>
                    """

                    components.html(drag_drop_script, height=230, scrolling=True)

                    st.markdown("---")
                    st.markdown("### 📋 Curatoriaal Rapport & Motivering")
                    
                    if st.session_state.get("curator_concept"):
                        st.info(f"💡 **Curatoriaal Visie & Concept:** {st.session_state['curator_concept']}")

                    st.success(f"Selectie voltooid! De AI heeft de **{len(sorted_items)} beste beelden** gekozen uit je werkset van {len(basket_items)} foto's.")

                    for s_item in sorted_items:
                        order_idx = s_item.get("position", 1)
                        orig_item = next((x for x in basket_items if x.get("id") == s_item["id"]), None)
                        
                        with st.container(border=True):
                            col_i1, col_i2 = st.columns([0.2, 0.8])
                            with col_i1:
                                if orig_item and orig_item.get("image_url"):
                                    st.image(orig_item.get("image_url"), use_container_width=True)
                            with col_i2:
                                role_tag = s_item.get("role_tag", "🖼️ Wandbeeld")

                                st.markdown(f"##### Positie #{order_idx}: **{s_item['titel']}** (`{role_tag}`)")
                                st.markdown(f"📍 **Locatie:** {s_item['locatie']} | **Score:** {s_item['score']}/100")
                                st.caption(f"Licht-dramatiek: {int(s_item['light_drama']*100 if s_item['light_drama']<=1 else s_item['light_drama'])}/100 | Melancholie: {int(s_item['melancholy']*100 if s_item['melancholy']<=1 else s_item['melancholy'])}/100")
                                st.markdown(f"**Curator motivering:** *{s_item.get('ai_motivering', 'Geen motivering beschikbaar.')}*")