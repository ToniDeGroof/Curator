import streamlit as st
import io
import json
import base64
import time
import re
import tempfile
import os
from PIL import Image, ImageOps
from supabase import create_client, Client
import openai
from fpdf import FPDF

# ==========================================
# CONFIGURATIE VOOR MODEL EN MODELNAAM
# ==========================================
OPENAI_MODEL_NAME = "gpt-4o" 

# ==========================================
# 1. CONFIGURATIE & DB VERBINDING (UIT SECRETS)
# ==========================================
st.set_page_config(page_title="Academie Foto Archief", layout="wide")

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
openai_api_key = st.secrets["OPENAI_API_KEY"]

st.markdown("""
    <style>
        html, body, [class*="css"], .stMarkdown, .stTextInput, .stTextArea, .stSelectbox, button {
            font-size: 15px !important;
            color: #000000 !important;
        }
        h1 { font-size: 1.8rem !important; color: #000000 !important; }
        h2 { font-size: 1.5rem !important; color: #000000 !important; }
        h3 { font-size: 1.2rem !important; color: #000000 !important; }
        
        .paper-view {
            background-color: #ffffff !important;
            color: #000000 !important;
            padding: 25px !important;
            border-radius: 4px !important;
            border: 1px solid #d0d7de !important;
            box-shadow: 0px 4px 12px rgba(0, 0, 0, 0.08) !important;
            font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif !important;
            font-size: 15px !important;
            line-height: 1.5 !important;
        }
        .profile-box {
            background-color: #f8f9fa !important;
            border-left: 4px solid #000000 !important;
            padding: 12px !important;
            margin-top: 15px !important;
            font-size: 14px !important;
        }
        
        .curator-card-info {
            font-size: 11px !important;
            line-height: 1.2 !important;
            text-align: center;
            margin-top: 4px;
            margin-bottom: 12px;
        }

        .curator-card-info strong {
            font-size: 11.5px !important;
            display: block;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .badge-wow {
            background-color: #ffebe9;
            color: #cf222e;
            padding: 1px 4px;
            border-radius: 3px;
            font-weight: bold;
            font-size: 9px;
            display: inline-block;
            margin-bottom: 2px;
        }
    </style>
""", unsafe_allow_html=True)

@st.cache_resource
def get_supabase_client():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = get_supabase_client()

defaults = {
    "current_index": 0,
    "last_module": "Straatfotografie",
    "last_datumcode": "202608",
    "last_locatie": "Boekarest",
    "last_kleurtype": "Kleur",
    "last_intentie": "",
    "analysis_result": None,
    "uploader_key": 0,
    # Curator filter statusen
    "curator_search_query": "",
    "curator_module": "Alle modules",
    "curator_locatie": "Alle locaties",
    "curator_datum": "Alle datums",
    "curator_formaat": "Alle formaten",
    "curator_kleurtype": "Alle kleurtypen",
    "curator_min_score": 0,
    "curator_light_drama": 0,
    "curator_melancholy": 0,
    "curator_intimacy": 0,
    "curator_eyecatchers": False
}

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value

def reset_curator_filters():
    st.session_state.curator_search_query = ""
    st.session_state.curator_module = "Alle modules"
    st.session_state.curator_locatie = "Alle locaties"
    st.session_state.curator_datum = "Alle datums"
    st.session_state.curator_formaat = "Alle formaten"
    st.session_state.curator_kleurtype = "Alle kleurtypen"
    st.session_state.curator_min_score = 0
    st.session_state.curator_light_drama = 0
    st.session_state.curator_melancholy = 0
    st.session_state.curator_intimacy = 0
    st.session_state.curator_eyecatchers = False

# ==========================================
# 2. HULPFUNCTIES
# ==========================================
def get_image_aspect_ratio(image_bytes):
    """Bepaalt de verhouding/aspect ratio van een afbeelding (rekening houdend met EXIF-orientatie)."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        # Vang EXIF rotatie op (bv. foto's van smartphones die anders gekanteld blijken)
        img = ImageOps.exif_transpose(img)
        w, h = img.size
        ratio = w / float(h)
        if ratio > 1.10:
            return "Liggend", ratio
        elif ratio < 0.90:
            return "Staand", ratio
        else:
            return "Vierkant", ratio
    except Exception:
        return "Onbekend", 1.0

def compress_image(image_bytes, max_size=(600, 600), quality=85):
    img = Image.open(io.BytesIO(image_bytes))
    img = ImageOps.exif_transpose(img)
    if img.mode != 'RGB':
        img = img.convert('RGB')
    img.thumbnail(max_size, Image.Resampling.LANCZOS)
    
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()

def format_profiel_summary(res):
    art = res.get("artistic_identity", {})
    emo = res.get("emotional_profile", {})
    cur = res.get("curatorial_profile", {})
    
    tones = ", ".join(emo.get("dominant_tones", []))
    features = ", ".join(art.get("distinctive_features", []))
    
    summary_parts = []
    if art.get("primary_character"):
        summary_parts.append(f"<b>Karakter:</b> {art.get('primary_character')}")
    if tones:
        summary_parts.append(f"<b>Dominante sfeer:</b> {tones}")
    if art.get("visual_voice"):
        summary_parts.append(f"<b>Visuele stem:</b> {art.get('visual_voice')}")
    if features:
        summary_parts.append(f"<b>Kenmerken:</b> {features}")
    if cur.get("exhibition_role"):
        summary_parts.append(f"<b>Curator-rol:</b> {cur.get('exhibition_role')}")
        
    return "<br>".join(summary_parts)

def generate_pdf_with_thumbnail(titel, module, locatie, datumcode, score, jurytekst, profiel_summary="", image_bytes=None):
    pdf = FPDF()
    pdf.add_page()
    
    tmp_path = None
    has_image = False
    
    if image_bytes:
        try:
            compressed_img = compress_image(image_bytes, max_size=(500, 500))
            fd, tmp_path = tempfile.mkstemp(suffix=".jpg")
            os.write(fd, compressed_img)
            os.close(fd)
            
            pdf.image(tmp_path, x=130, y=12, w=60)
            has_image = True
        except Exception:
            pass

    pdf.set_font("helvetica", "B", 20)
    pdf.cell(115, 10, txt="Analyseverslag", ln=1)
    
    pdf.set_font("helvetica", "B", 14)
    pdf.cell(115, 8, txt=f"Eindscore: {score}/100", ln=1)
    
    pdf.set_font("helvetica", "", 11)
    clean_meta = f"Module: {module} | Locatie: {locatie} | Datum: {datumcode}".encode('latin-1', 'replace').decode('latin-1')
    pdf.cell(115, 6, txt=clean_meta, ln=1)
    
    if has_image:
        pdf.set_y(78)
    else:
        pdf.ln(8)
    
    lines = jurytekst.split('\n')
    for line in lines:
        clean_line = line.replace("•", "-").encode('latin-1', 'replace').decode('latin-1').strip()
        
        if not clean_line:
            pdf.ln(2)
            continue
            
        if clean_line.startswith("**"):
            header_text = clean_line.replace("**", "").strip()
            if re.match(r'^\d+\.', header_text):
                pdf.set_font("helvetica", "B", 13)
                pdf.ln(3)
                pdf.multi_cell(0, 7, txt=header_text)
                pdf.set_font("helvetica", "", 11)
                pdf.ln(1)
            else:
                pdf.set_font("helvetica", "B", 11)
                pdf.multi_cell(0, 6, txt=header_text)
                pdf.set_font("helvetica", "", 11)
        else:
            normal_text = clean_line.replace("**", "")
            if normal_text.startswith("Score:") or normal_text.startswith("Totaalscore:"):
                pdf.set_font("helvetica", "B", 10.5)
                pdf.multi_cell(0, 6, txt=normal_text)
                pdf.set_font("helvetica", "", 11)
                pdf.ln(2)
            else:
                pdf.set_font("helvetica", "", 11)
                pdf.multi_cell(0, 6, txt=normal_text)
                pdf.ln(1)

    if profiel_summary:
        pdf.ln(4)
        pdf.set_font("helvetica", "B", 11)
        pdf.multi_cell(0, 6, txt="Artistiek & Curatoriaal Profiel:")
        pdf.set_font("helvetica", "I", 10)
        clean_p = profiel_summary.replace("<b>", "").replace("</b>", "").replace("<br>", "\n").encode('latin-1', 'replace').decode('latin-1')
        pdf.multi_cell(0, 5, txt=clean_p)

    out = pdf.output(dest='S')
    
    if tmp_path and os.path.exists(tmp_path):
        try:
            os.remove(tmp_path)
        except Exception:
            pass

    if isinstance(out, str):
        return out.encode('latin-1')
    return bytes(out)

def analyze_photo_with_custom_prompt(image_bytes, api_key, titel, locatie, module, kleurtype, str_intentie):
    client = openai.OpenAI(api_key=api_key)
    base64_image = base64.b64encode(compress_image(image_bytes, max_size=(600, 600))).decode('utf-8')
    
    formaat, aspect_ratio = get_image_aspect_ratio(image_bytes)

    superprompt = f"""
Persona: Je bent een ervaren, analytische en veeleisende fotorecensent en curator aan een academie voor beeldende kunst. Beoordeel het beeld volgens onderstaande criteria én stel een uitgebreid multi-laags profiel op voor latere curatoriale analyse.

Context van de foto:
- Titel: {titel}
- Locatie: {locatie}
- Module: {module}
- Kleurtype: {kleurtype}
- Formaat: {formaat} (verhouding {aspect_ratio:.2f})
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
        "kleurtype": "{kleurtype}",
        "formaat": "{formaat}"
    }},
    "jurytekst": "**1. Analyse per criterium**\\n..."
}}
"""
    
    response = client.chat.completions.create(
        model=OPENAI_MODEL_NAME,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": superprompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
        ]}],
        response_format={"type": "json_object"},
        max_tokens=3500,
        temperature=0.3
    )
    
    parsed_json = json.loads(response.choices[0].message.content)
    
    deelscores = parsed_json.get("deelscores", {})
    berekende_eindscore = sum(deelscores.values()) if deelscores else 50
    parsed_json["eindscore"] = berekende_eindscore
    
    if "meta_info" not in parsed_json:
        parsed_json["meta_info"] = {"kleurtype": kleurtype, "formaat": formaat}
    
    return parsed_json

def save_beoordeling_to_db(titel, locatie, datumcode, module, image_url, totaal_score, jurytekst, full_json_data):
    data = {
        "titel": titel,
        "locatie": locatie,
        "datumcode": datumcode,
        "module": module,
        "image_url": image_url,
        "totaal_score": totaal_score,
        "jurytekst": jurytekst,
        "artistiek_profiel": json.dumps(full_json_data)
    }
    return supabase.table("beoordelingen").insert(data).execute().data

def get_all_beoordelingen():
    return supabase.table("beoordelingen").select("*").order("created_at", desc=True).execute().data

def delete_beoordeling_from_db(item_id):
    return supabase.table("beoordelingen").delete().eq("id", item_id).execute().data

# ==========================================
# 3. STREAMLIT GEBRUIKERSINTERFACE
# ==========================================
st.title("Academie Foto Analyse & Curator Module")

tab1, tab2, tab3 = st.tabs(["Foto Analyse & Invoer", "Academie Archief", "Curator Module"])

# ------------------------------------------
# TAB 1: ANALYSE & INVOER
# ------------------------------------------
with tab1:
    st.subheader("1. Selecteer Reeks Foto's")
    
    uploaded_files = st.file_uploader(
        "Kies één of meerdere foto's", 
        type=["jpg", "jpeg", "png"], 
        accept_multiple_files=True,
        key=f"uploader_{st.session_state.uploader_key}"
    )

    if uploaded_files:
        total_files = len(uploaded_files)
        
        if st.session_state.current_index >= total_files:
            st.success(f"Alle {total_files} foto's uit deze reeks zijn verwerkt.")
            if st.button("Nieuwe selectie maken", type="primary"):
                st.session_state.current_index = 0
                st.session_state.analysis_result = None
                st.session_state.uploader_key += 1
                st.rerun()
        else:
            current_file = uploaded_files[st.session_state.current_index]
            st.info(f"Foto {st.session_state.current_index + 1} van {total_files}: **{current_file.name}**")
            
            col_preview, col_inputs = st.columns([0.35, 0.65])
            
            with col_preview:
                st.image(current_file, use_container_width=True)

            with col_inputs:
                st.markdown("#### Meta-gegevens")
                titel = current_file.name
                
                col_f1, col_f2 = st.columns(2)
                with col_f1:
                    module = st.text_input("Module", value=st.session_state.last_module)
                    datumcode = st.text_input("Datumcode (YYYYMM)", value=st.session_state.last_datumcode)
                
                with col_f2:
                    locatie = st.text_input("Locatie", value=st.session_state.last_locatie)
                    kleur_list = ["Kleur", "Zwart-wit", "Monochroom"]
                    kleur_index = kleur_list.index(st.session_state.last_kleurtype) if st.session_state.last_kleurtype in kleur_list else 0
                    kleurtype = st.selectbox("Kleurtype", kleur_list, index=kleur_index)

                st.session_state.last_module = module
                st.session_state.last_datumcode = datumcode
                st.session_state.last_locatie = locatie
                st.session_state.last_kleurtype = kleurtype

                str_intentie = st.text_area(
                    "Intentie van de fotograaf", 
                    value=st.session_state.last_intentie, 
                    placeholder="Wat wou je tonen of overbrengen?",
                    height=90
                )

            st.container()

            if st.session_state.analysis_result is None:
                if st.button(f"Start Analyse (Foto {st.session_state.current_index + 1}/{total_files})", type="primary"):
                    with st.spinner("Beoordeling & Multi-laags Artistiek Profiel genereren..."):
                        try:
                            file_bytes = current_file.read()
                            ai_result = analyze_photo_with_custom_prompt(
                                file_bytes, openai_api_key, titel, locatie, 
                                module, kleurtype, str_intentie
                            )
                            st.session_state.analysis_result = ai_result
                            st.rerun()
                        except Exception as e:
                            st.error(f"Fout bij analyseren: {e}")

            else:
                result = st.session_state.analysis_result
                score = result.get("eindscore", 50)
                jurytekst = result.get("jurytekst", "")
                
                html_formatted = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', jurytekst)
                formatted_html = html_formatted.replace('\n', '<br>')
                
                summary_html = format_profiel_summary(result)
                
                paper_content = f"""<div class="paper-view">
<h2 style="margin-top:0; color:#000000;">Analyseverslag</h2>
<h3 style="color:#000000; margin-bottom:25px;">Eindscore: {score}/100</h3>
{formatted_html}
<div class="profile-box">
<strong>Artistiek & Curatoriaal Profiel:</strong><br>
{summary_html}
</div>
</div>"""

                st.markdown(paper_content, unsafe_allow_html=True)

                c1, c2, c3, c4 = st.columns(4)
                
                current_file.seek(0)
                raw_file_bytes = current_file.read()

                with c1:
                    if st.button("Opslaan in database", use_container_width=True, type="primary"):
                        with st.spinner("Opslaan in database..."):
                            filename = f"{int(time.time())}_{current_file.name}"
                            path_on_supa = f"academie/{filename}"
                            compressed_bytes = compress_image(raw_file_bytes)
                            supabase.storage.from_("fotos").upload(
                                path=path_on_supa,
                                file=compressed_bytes,
                                file_options={"content-type": "image/jpeg", "x-upsert": "true"}
                            )
                            public_url = supabase.storage.from_("fotos").get_public_url(path_on_supa)
                            save_beoordeling_to_db(titel, locatie, datumcode, module, public_url, score, jurytekst, result)
                            st.success("Opgeslagen met het volledige curatieve profiel!")
                            time.sleep(0.5)

                with c2:
                    pdf_data = generate_pdf_with_thumbnail(titel, module, locatie, datumcode, score, jurytekst, summary_html, raw_file_bytes)
                    st.download_button(
                        label="PDF Genereren",
                        data=pdf_data,
                        file_name=f"Analyse_{titel}.pdf",
                        mime="application/pdf",
                        use_container_width=True
                    )

                with c3:
                    if st.button("Volgende beoordelen", use_container_width=True):
                        st.session_state.analysis_result = None
                        st.session_state.last_intentie = ""
                        st.session_state.current_index += 1
                        st.rerun()

                with c4:
                    if st.button("Nieuwe selectie maken", use_container_width=True):
                        st.session_state.current_index = 0
                        st.session_state.analysis_result = None
                        st.session_state.uploader_key += 1
                        st.rerun()

# ------------------------------------------
# TAB 2: ARCHIEF
# ------------------------------------------
with tab2:
    st.subheader("Academie Archief")
    if st.button("Ververs Archief"):
        st.rerun()

    try:
        items = get_all_beoordelingen()
        if not items:
            st.info("Er staan nog geen foto's in de database.")
        else:
            for item in items:
                with st.expander(f"{item.get('titel')} — Score: {item.get('totaal_score')}/100 ({item.get('datumcode')})"):
                    col_a1, col_a2 = st.columns([0.3, 0.7])
                    with col_a1:
                        st.image(item.get("image_url"), use_container_width=True)
                        st.caption(f"Locatie: {item.get('locatie')} | Module: {item.get('module')}")
                    with col_a2:
                        st.markdown(item.get('jurytekst'))
                        
                        raw_p = item.get('artistiek_profiel')
                        if raw_p:
                            try:
                                p_dict = json.loads(raw_p) if isinstance(raw_p, str) else raw_p
                                summary = format_profiel_summary(p_dict)
                                st.info(f"**Artistiek & Curatoriaal Profiel:**<br>{summary}")
                            except Exception:
                                pass
                                
                    if st.button("Verwijder uit archief", key=f"del_{item.get('id')}"):
                        delete_beoordeling_from_db(item.get('id'))
                        st.rerun()
    except Exception as e:
        st.error(f"Fout bij laden archief: {e}")

# ------------------------------------------
# TAB 3: CURATOR MODULE
# ------------------------------------------
with tab3:
    st.subheader("Curatoriale Collectie-Analyse & Selectie")

    try:
        all_items = get_all_beoordelingen()
        
        if not all_items:
            st.warning("Er staan nog geen foto's in het archief om te cureren.")
        else:
            # RESET KNOP BOVENAAN
            c_top_1, c_top_2 = st.columns([0.75, 0.25])
            with c_top_2:
                if st.button("🔄 Reset alle filters", use_container_width=True):
                    reset_curator_filters()
                    st.rerun()

            with c_top_1:
                search_query = st.text_input(
                    "🔍 Slim zoeken / Zoekopdracht", 
                    key="curator_search_query",
                    placeholder="Bijv. 'hou de 7 beste over', 'top 10', 'rustig', 'boekarest'..."
                ).lower().strip()

            # "Top N" detectie uit de zoekbalk
            top_n_requested = None
            top_n_match = re.search(r'(\d+)\s*(beste|hoogste|top)|top\s*(\d+)', search_query)
            if top_n_match:
                top_n_requested = int(top_n_match.group(1) or top_n_match.group(3))

            # Dynamic dropdown opties
            existing_modules = ["Alle modules"] + sorted(list(set([item.get("module") for item in all_items if item.get("module")])))
            existing_locations = ["Alle locaties"] + sorted(list(set([item.get("locatie") for item in all_items if item.get("locatie")])))
            existing_dates = ["Alle datums"] + sorted(list(set([item.get("datumcode") for item in all_items if item.get("datumcode")])))

            # UITBREIDBAAR FILTERPANEEL
            with st.expander("⚙️ Uitgebreide Filters & Kenmerken", expanded=True):
                c_f1, c_f2, c_f3, c_f4 = st.columns(4)
                
                with c_f1:
                    sel_module = st.selectbox("Module", existing_modules, key="curator_module")
                    sel_locatie = st.selectbox("Locatie", existing_locations, key="curator_locatie")
                    sel_datum = st.selectbox("Datumcode (YYYYMM)", existing_dates, key="curator_datum")

                with c_f2:
                    sel_formaat = st.selectbox("Formaat", ["Alle formaten", "Staand", "Liggend", "Vierkant"], key="curator_formaat")
                    sel_kleurtype = st.selectbox("Kleurtype", ["Alle kleurtypen", "Kleur", "Zwart-wit", "Monochroom"], key="curator_kleurtype")

                with c_f3:
                    min_score = st.slider("Minimale Eindscore", 0, 100, key="curator_min_score")
                    min_light_drama = st.slider("Min. Licht-dramatiek", 0, 100, key="curator_light_drama")
                    only_eyecatchers = st.checkbox("🌟 Alleen 'Eyecatchers'", key="curator_eyecatchers")

                with c_f4:
                    min_melancholy = st.slider("Min. Melancholie-score", 0, 100, key="curator_melancholy")
                    min_intimacy = st.slider("Min. Intimiteit-score", 0, 100, key="curator_intimacy")

            # FILTERLOGICA
            filtered_items = []
            
            for item in all_items:
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

                # Kleurtype check
                item_kleurtype = meta_info.get("kleurtype", "")
                if sel_kleurtype != "Alle kleurtypen" and item_kleurtype and sel_kleurtype.lower() not in item_kleurtype.lower():
                    continue

                # Formaat check
                item_formaat = meta_info.get("formaat", "")
                if sel_formaat != "Alle formaten" and item_formaat and sel_formaat.lower() != item_formaat.lower():
                    continue

                # Vrije tekst-check (alleen uitvoeren als er geen getalsmatige "top X" instructie in staat)
                if search_query and not top_n_requested:
                    words = [w for w in search_query.split() if len(w) > 2]
                    text_to_search = f"{item.get('titel', '')} {item.get('module', '')} {item.get('locatie', '')} {item.get('datumcode', '')} {item.get('jurytekst', '')} {artistic.get('primary_character', '')} {artistic.get('visual_voice', '')} {' '.join(emotional.get('dominant_tones', []))}".lower()
                    
                    if words and not any(w in text_to_search for w in words):
                        continue

                # Meta-filters
                if sel_module != "Alle modules" and item.get("module") != sel_module:
                    continue
                if sel_locatie != "Alle locaties" and item.get("locatie") != sel_locatie:
                    continue
                if sel_datum != "Alle datums" and item.get("datumcode") != sel_datum:
                    continue

                # Score filter
                item_score = item.get("totaal_score") or 0
                if item_score < min_score:
                    continue

                # Schuifbalken
                light_drama_val = float(formal.get("light_drama", 0)) * 100
                melancholy_val = float(emotional.get("melancholy", 0)) * 100
                intimacy_val = float(emotional.get("intimacy", 0)) * 100

                if light_drama_val < min_light_drama:
                    continue
                if melancholy_val < min_melancholy:
                    continue
                if intimacy_val < min_intimacy:
                    continue

                # Eyecatcher filter
                is_eyecatcher = (item_score >= 82) or (light_drama_val >= 75) or ("openingsbeeld" in curatorial.get("exhibition_role", "").lower())
                if only_eyecatchers and not is_eyecatcher:
                    continue

                filtered_items.append((item, p_dict, is_eyecatcher))

            # Sorteer altijd op totaal_score (hoogste eerst)
            filtered_items.sort(key=lambda x: x[0].get("totaal_score") or 0, reverse=True)

            # Als er een "Top N" is meegegeven, snijd de gefilterde lijst af
            if top_n_requested and top_n_requested > 0:
                filtered_items = filtered_items[:top_n_requested]
                st.info(f"💡 Zoekopdracht herkend: Bovenste **{len(filtered_items)}** beelden geselecteerd die voldoen aan de gekozen filters.")

            # WEERGAVE RESULTATEN
            st.markdown(f"---")
            st.markdown(f"### Selectie: **{len(filtered_items)}** van **{len(all_items)}** beelden")

            if not filtered_items:
                st.info("Geen beelden gevonden die voldoen aan alle gekozen criteria. Klik op '🔄 Reset alle filters' om opnieuw te beginnen.")
            else:
                cols = st.columns(8)
                for idx, (item, p_dict, is_eyecatcher) in enumerate(filtered_items):
                    col = cols[idx % 8]
                    meta_info = p_dict.get("meta_info", {})
                    fmt_label = meta_info.get("formaat", "")
                    
                    with col:
                        st.image(item.get("image_url"), use_container_width=True)
                        st.markdown(f'''
                            <div class="curator-card-info">
                                {'<span class="badge-wow">🌟 WOW</span>' if is_eyecatcher else ''}
                                <strong>{item.get('titel')}</strong>
                                <span style="color: #666;">⭐ <b>{item.get('totaal_score')}</b> | {fmt_label}</span>
                            </div>
                        ''', unsafe_allow_html=True)

    except Exception as e:
        st.error(f"Fout bij het laden van de Curator Module: {e}")