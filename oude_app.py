import base64
import io
import os
import re
import tempfile
from openai import OpenAI
from fpdf import FPDF
from PIL import Image
import streamlit as st

# -----------------------------------------------------------------------------
# 1. PAGINA CONFIGURATIE & STYLING
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="F-Art Fotoclub - Beoordeling",
    page_icon="",
    layout="centered",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    /* Witruimte aan de bovenkant van de pagina (~1 cm extra) */
    .block-container {
        padding-top: 3.5rem !important;
        padding-bottom: 1rem !important;
    }
    
    /* Fijn donker randje om de afbeeldingen */
    .stImage img {
        border: 1px solid #94a3b8 !important;
        border-radius: 6px;
    }
    
    /* Infobalk styling */
    .info-box {
        background-color: #eef6ff;
        border-left: 5px solid #1E3A8A;
        padding: 10px 20px;
        border-radius: 5px;
        margin-bottom: 20px;
    }
    
    .info-box ul {
        margin-top: 5px;
        margin-bottom: 10px;
        padding-left: 20px;
    }
</style>
""", unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# 2. HELPER FUNCTIES (PDF & PARSING)
# -----------------------------------------------------------------------------

class PDFRapport(FPDF):
    def header(self):
        self.set_font('Helvetica', 'B', 9)
        self.set_text_color(100, 100, 100)
        self.cell(0, 5, 'F-ART FOTOCLUB - AI JURYRAPPORT', 0, 1, 'R')
        self.set_draw_color(220, 220, 220)
        self.line(10, 12, 200, 12)
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f'Pagina {self.page_no()}/{{nb}}', 0, 0, 'C')


def opschonen_voor_pdf(tekst):
    """Zorgt ervoor dat vreemde leestekens en emoticons de PDF-generator niet laten crashen."""
    if not tekst:
        return ""
    tekst = str(tekst).replace('“', '"').replace('”', '"').replace("’", "'").replace("‘", "'")
    return tekst.encode("latin-1", "ignore").decode("latin-1")


def parse_curator_rapport(rapport_tekst):
    """Splitst het curator rapport op in geselecteerde, niet-geselecteerde foto's en overkoepelend oordeel."""
    sectie_1 = []
    sectie_2 = []
    sectie_3 = ""
    huidige_sectie = None

    for regel in rapport_tekst.split("\n"):
        regel_str = regel.strip()
        if "SECTIE 1" in regel_str.upper():
            huidige_sectie = 1
            continue
        elif "SECTIE 2" in regel_str.upper():
            huidige_sectie = 2
            continue
        elif "SECTIE 3" in regel_str.upper():
            huidige_sectie = 3
            continue

        if me := re.search(r"FOTO_(\d+)", regel_str, re.IGNORECASE):
            foto_id = f"FOTO_{me.group(1)}"
            if "Reden:" in regel_str:
                reden = regel_str.split("Reden:", 1)[1].strip()
            elif "-" in regel_str:
                reden = regel_str.split("-", 1)[1].strip()
            else:
                reden = regel_str

            if huidige_sectie == 1:
                sectie_1.append((foto_id, reden))
            elif huidige_sectie == 2:
                sectie_2.append((foto_id, reden))
        elif huidige_sectie == 3:
            sectie_3 += regel + "\n"

    return sectie_1, sectie_2, sectie_3.strip()


def maak_pdf_rapport(titel, metadata_dict, rapport_tekst, uploaded_file=None):
    """PDF-generator voor Optie 1 (Individuele Beoordeling)."""
    pdf = PDFRapport()
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(30, 58, 138)
    pdf.cell(0, 10, opschonen_voor_pdf(titel), ln=True)
    pdf.ln(2)

    if uploaded_file is not None:
        tmp_path = None
        try:
            uploaded_file.seek(0)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp_img:
                img = Image.open(uploaded_file)
                if img.mode != "RGB":
                    img = img.convert("RGB")
                img.save(tmp_img.name, format="PNG")
                tmp_path = tmp_img.name

            pdf.image(tmp_path, x=75, w=60)
            pdf.ln(5)
        except Exception:
            pass
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    pdf.set_fill_color(240, 244, 248)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(50, 50, 50)
    pdf.cell(0, 6, "METADATA & PARAMETERS", ln=True, fill=True)

    pdf.set_font("Helvetica", "", 9)
    for sleutel, waarde in metadata_dict.items():
        regel = f"{sleutel}: {waarde}"
        pdf.multi_cell(0, 5, opschonen_voor_pdf(regel))
    pdf.ln(5)

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(20, 20, 20)

    regels = rapport_tekst.split("\n")
    for regel in regels:
        schone_regel = opschonen_voor_pdf(regel)
        if schone_regel.strip().startswith("**") and schone_regel.strip().endswith("**"):
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", 11)
            pdf.set_text_color(30, 58, 138)
            pdf.multi_cell(0, 6, schone_regel.replace("**", ""))
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(20, 20, 20)
        else:
            pdf.multi_cell(0, 5, schone_regel)

    pdf_bytes = pdf.output(dest="S").encode("latin-1", "replace")
    return io.BytesIO(pdf_bytes)


def maak_curator_pdf_rapport(titel, metadata_dict, sectie_1_matches, sectie_2_matches, sectie_3_txt, id_to_file):
    """PDF-generator voor Optie 2 (Curator Expositie Selectie) met miniaturen op de PDF."""
    pdf = PDFRapport()
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    pdf.set_font('Helvetica', 'B', 16)
    pdf.set_text_color(30, 58, 138)
    pdf.cell(0, 10, opschonen_voor_pdf(titel), ln=True)
    pdf.ln(2)

    pdf.set_fill_color(240, 244, 248)
    pdf.set_font('Helvetica', 'B', 10)
    pdf.set_text_color(50, 50, 50)
    pdf.cell(0, 6, "METADATA & EXPOSITIE PARAMETERS", ln=True, fill=True)
    
    pdf.set_font('Helvetica', '', 9)
    for sleutel, waarde in metadata_dict.items():
        regel = f"{sleutel}: {waarde}"
        pdf.multi_cell(0, 5, opschonen_voor_pdf(regel))
    pdf.ln(5)

    def print_foto_items(titel_sectie, matches):
        pdf.set_font('Helvetica', 'B', 12)
        pdf.set_text_color(30, 58, 138)
        pdf.cell(0, 8, opschonen_voor_pdf(titel_sectie), ln=True)
        pdf.set_draw_color(200, 200, 200)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(3)

        seen_ids = set()
        count = 1

        for foto_num, reden in matches:
            foto_id = foto_num if foto_num.startswith("FOTO_") else f"FOTO_{foto_num}"
            if foto_id in seen_ids:
                continue
            seen_ids.add(foto_id)

            target_file = id_to_file.get(foto_id)
            display_name = target_file.name if target_file else foto_id
            
            start_y = pdf.get_y()
            if start_y > 230:
                pdf.add_page()
                start_y = pdf.get_y()

            img_height = 0
            if target_file is not None:
                try:
                    target_file.seek(0)
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp_img:
                        img = Image.open(target_file)
                        if img.mode != 'RGB':
                            img = img.convert('RGB')
                        img.save(tmp_img.name, format="PNG")
                        tmp_path = tmp_img.name
                    
                    pdf.image(tmp_path, x=10, y=start_y, w=35)
                    img_height = (img.height / img.width) * 35 if img.width > 0 else 30
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except Exception:
                    img_height = 0

            pdf.set_x(48)
            pdf.set_font('Helvetica', 'B', 9)
            pdf.set_text_color(30, 58, 138)
            
            if "Geselecteerd" in titel_sectie:
                pdf.multi_cell(152, 4, opschonen_voor_pdf(f"Positie {count} op de wand: {display_name} ({foto_id})"))
            else:
                pdf.multi_cell(152, 4, opschonen_voor_pdf(f"Foto: {display_name} ({foto_id})"))

            pdf.set_x(48)
            pdf.set_font('Helvetica', '', 8.5)
            pdf.set_text_color(40, 40, 40)
            pdf.multi_cell(152, 4, opschonen_voor_pdf(f"Motivatie: {reden.strip()}"))

            text_height = pdf.get_y() - start_y
            next_y = start_y + max(img_height, text_height) + 6
            pdf.set_y(next_y)
            count += 1
        pdf.ln(3)

    if sectie_1_matches:
        print_foto_items("1. GESELECTEERDE BEELDEN (WANDVOLGORDE)", sectie_1_matches)

    if sectie_2_matches:
        print_foto_items("2. NIET-GESELECTEERDE BEELDEN", sectie_2_matches)

    if sectie_3_txt:
        if pdf.get_y() > 220:
            pdf.add_page()
        pdf.set_font('Helvetica', 'B', 12)
        pdf.set_text_color(30, 58, 138)
        pdf.cell(0, 8, "3. OVERKOEPELEND OORDEEL CURATOR", ln=True)
        pdf.set_draw_color(200, 200, 200)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(3)

        pdf.set_font('Helvetica', '', 9.5)
        pdf.set_text_color(20, 20, 20)
        schone_oordeel = opschonen_voor_pdf(sectie_3_txt.replace("SECTIE 3: OVERKOEPELEND OORDEEL", "").strip())
        pdf.multi_cell(0, 5, schone_oordeel)

    pdf_bytes = pdf.output(dest="S").encode("latin-1", "replace")
    return io.BytesIO(pdf_bytes)


def maak_reeks_pdf_rapport(titel, metadata_dict, rapport_tekst, uploaded_files):
    """PDF-generator voor Optie 3 (Reeks-Analyse)."""
    pdf = PDFRapport()
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(30, 58, 138)
    pdf.cell(0, 10, opschonen_voor_pdf(titel), ln=True)
    pdf.ln(2)

    pdf.set_fill_color(240, 244, 248)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(50, 50, 50)
    pdf.cell(0, 6, "METADATA & REEKS PARAMETERS", ln=True, fill=True)

    pdf.set_font("Helvetica", "", 9)
    for sleutel, waarde in metadata_dict.items():
        regel = f"{sleutel}: {waarde}"
        pdf.multi_cell(0, 5, opschonen_voor_pdf(regel))
    pdf.ln(5)

    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(30, 58, 138)
    pdf.cell(0, 6, "AANGEBODEN FOTOREEKS", ln=True)
    pdf.ln(2)

    x_start = 10
    y_start = pdf.get_y()
    thumb_w = 25

    for idx, f in enumerate(uploaded_files[:6]):
        try:
            f.seek(0)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp_img:
                img = Image.open(f)
                if img.mode != "RGB":
                    img = img.convert("RGB")
                img.save(tmp_img.name, format="PNG")
                tmp_path = tmp_img.name

            pdf.image(tmp_path, x=x_start + (idx * 30), y=y_start, w=thumb_w)
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass

    pdf.set_y(y_start + 30)

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(20, 20, 20)

    regels = rapport_tekst.split("\n")
    for regel in regels:
        schone_regel = opschonen_voor_pdf(regel)
        if schone_regel.strip().startswith("**") and schone_regel.strip().endswith("**"):
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", 11)
            pdf.set_text_color(30, 58, 138)
            pdf.multi_cell(0, 6, schone_regel.replace("**", ""))
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(20, 20, 20)
        else:
            pdf.multi_cell(0, 5, schone_regel)

    pdf_bytes = pdf.output(dest="S").encode("latin-1", "replace")
    return io.BytesIO(pdf_bytes)


# -----------------------------------------------------------------------------
# 3. AI GENERATIE FUNCTIES
# -----------------------------------------------------------------------------

def encode_image_to_base64(uploaded_file):
    bytes_data = uploaded_file.getvalue()
    return base64.b64encode(bytes_data).decode("utf-8")


def genereer_individuele_analyse(api_key, image_base64, gekozen_genre, kleurtype, str_intentie, str_context, str_techniek):
    client = OpenAI(api_key=api_key)
    superprompt = f"""
Je bent een professionele fotografiejury. Analyseer grondig en constructief.
Metadata: Genre: {gekozen_genre}, Kleurtype: {kleurtype}, Intentie: {str_intentie}, Context: {str_context}, Techniek: {str_techniek}.

OPMAAKREGELS:
- Maak elk van de 11 genummerde kopjes ALTIJD VETGEDRUKT met dubbele asteriksen (**1. Intentie & Context**, etc.).
- Gebruik GEEN emojis in de gegenereerde tekst.

**1. Intentie & Context**
**2. Genre-analyse**
**3. Compositie, standpunt & beeldopbouw**
**4. Licht, schaduw & kleur**
**5. Technische vaardigheid**
**6. Narratief & psychologische lading**
**7. Visuele & emotionele impact**
**8. Verbeterpunten (concreet en uitvoerbaar)**
**9. Score (1-100) basisberekening**
**10. Genre-correctie (factor toepassen)**
**11. Eindscore tonen**

EINDSCORE: [getal]"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": [
            {"type": "text", "text": superprompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
        ]}],
        max_tokens=2000,
        temperature=0.3,
    )
    return response.choices[0].message.content


def genereer_curator_analyse(api_key, uploaded_files, aantal_gewenst, gekozen_genre, str_intentie, str_context):
    client = OpenAI(api_key=api_key)
    content_list = [{
        "type": "text",
        "text": f"Selecteer EXACT {aantal_gewenst} foto's uit {len(uploaded_files)} voor een expositie.\n"
                f"Metadata: Genre: {gekozen_genre}, Intentie: {str_intentie}, Context: {str_context}.\n"
                "STRUCTUREER STRIKT MET DE VOLGENDE DRIE SECTIES:\n"
                "SECTIE 1: GESELECTEERDE BEELDEN (Formaat per regel: '[GESELECTEERD] ID: FOTO_X - Reden: <motivering>')\n"
                "SECTIE 2: NIET-GESELECTEERDE BEELDEN (Formaat per regel: '[AFGEWEZEN] ID: FOTO_X - Reden: <reden>')\n"
                "SECTIE 3: OVERKOEPELEND OORDEEL"
    }]

    for idx, file in enumerate(uploaded_files):
        file.seek(0)
        img_b64 = encode_image_to_base64(file)
        file.seek(0)
        content_list.append({"type": "text", "text": f"Dit is FOTO_{idx+1} ({file.name}):"})
        content_list.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}", "detail": "low"}})

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": content_list}],
        max_tokens=2500,
        temperature=0.3,
    )
    return response.choices[0].message.content


def genereer_reeks_analyse(api_key, images_b64_list, bestandsnamen, gekozen_genre, str_intentie, str_context):
    client = OpenAI(api_key=api_key)
    prompt = f"""
Beoordeel een reeks van {len(images_b64_list)} foto's. Bestandsnamen: {", ".join(bestandsnamen)}.
Metadata: Genre: {gekozen_genre}, Intentie: {str_intentie}, Context: {str_context}.

EVALUEER OP:
1. **Samenhang & Visuele Rode Draad**
2. **Narratief & Verhaallijn**
3. **Ritme & Variatie**
4. **Sterke & Zwakke Schakels**
5. **Aanbevelingen voor Volgorde/Selectie**
6. **Reeks Eindscore (1-100)**

EINDSCORE: [getal]"""

    content_list = [{"type": "text", "text": prompt}]
    for b64 in images_b64_list:
        content_list.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": content_list}],
        max_tokens=2500,
        temperature=0.3,
    )
    return response.choices[0].message.content


# -----------------------------------------------------------------------------
# 4. SESSIE NAVIGATIE & SIDEBAR
# -----------------------------------------------------------------------------
if "huidig_scherm" not in st.session_state:
    st.session_state["huidig_scherm"] = "HOME"

def ga_naar_scherm(scherm_naam):
    st.session_state["huidig_scherm"] = scherm_naam
    st.rerun()

with st.sidebar:
    st.title("Navigatie")
    if st.button("Startscherm", key="btn_sidebar_home", use_container_width=True):
        ga_naar_scherm("HOME")
    st.divider()

    api_key_input = st.text_input(
        "OpenAI API Key:",
        type="password",
        help="Voer je API-sleutel in om foto's te kunnen analyseren.",
    )
    if api_key_input:
        st.session_state["openai_api_key"] = api_key_input
        st.caption("API Key ingesteld")
    else:
        st.caption("⚠️ API Key vereist voor analyse")

    st.divider()
    st.caption("Status: 🟢 Applicatie actief")


# -----------------------------------------------------------------------------
# 5. STARTSCHERM HOME
# -----------------------------------------------------------------------------
if st.session_state["huidig_scherm"] == "HOME":
    st.markdown("<h2 style='text-align: left; color: #1E3A8A; margin-bottom: 15px;'>F-Art Fotoclub - Beoordelingsplatform</h2>", unsafe_allow_html=True)

    st.markdown("""
    <div class='info-box'>
        <h4 style='margin-top:0; margin-bottom: 0; color: #1E3A8A;'>ℹ️ Hoe werkt dit platform?</h4>
        <ul>
            <li><strong>Stap 1:</strong> Maak hieronder een keuze uit Optie 1, 2 of 3.</li>
            <li><strong>Stap 2:</strong> Upload je foto's op de volgende pagina.</li>
            <li><strong>Stap 3:</strong> Ontvang direct een uitgebreid juryrapport.</li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("<h4 style='text-align: center; color: #1E3A8A; margin-top:0; margin-bottom:8px;'>Optie 1: Foto's</h4>", unsafe_allow_html=True)
        st.image("foto-1.jpg", use_container_width=True)
        st.write("Laat 1 tot 10 foto's één voor één in detail beoordelen op visuele impact, techniek, compositie en kleurbeheer")
        if st.button("**Start Individuele Beoordeling**", key="btn_optie1", type="primary", use_container_width=True):
            ga_naar_scherm("SCHERM_A")

    with col2:
        st.markdown("<h4 style='text-align: center; color: #1E3A8A; margin-top:0; margin-bottom:8px;'>Optie 2: Curator</h4>", unsafe_allow_html=True)
        st.image("foto-2.jpg", use_container_width=True)
        st.write("Upload 4 tot 20 foto's en kies het gewenste aantal voor een expo. De curator kiest de beste beelden.")
        if st.button("**Start Curator Selectie**", key="btn_optie2", type="primary", use_container_width=True):
            ga_naar_scherm("SCHERM_B1")

    with col3:
        st.markdown("<h4 style='text-align: center; color: #1E3A8A; margin-top:0; margin-bottom:8px;'>Optie 3: Reeks</h4>", unsafe_allow_html=True)
        st.image("foto-3.jpg", use_container_width=True)
        st.write("Werk je aan een serie? Upload 4 tot 20 foto's en wij nemen de samenhang en verhaallijn onder de loep.")
        if st.button("**Start Reeks-Analyse**", key="btn_optie3", type="primary", use_container_width=True):
            ga_naar_scherm("SCHERM_B2")


# -----------------------------------------------------------------------------
# 6. OPTIE 1: INDIVIDUELE FOTO BEOORDELING
# -----------------------------------------------------------------------------
if st.session_state["huidig_scherm"] == "SCHERM_A":
    st.header("Optie 1: Beoordeling Individuele Foto's")
    uploaded_files = st.file_uploader("Kies 1 tot maximaal 10 afbeeldingen (Je kunt achteraf nog foto's toevoegen of verwijderen):", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True)

    if uploaded_files:
        if len(uploaded_files) > 10:
            st.error(f"⚠️ Je hebt **{len(uploaded_files)} foto's** geselecteerd. Maximaal 10 toegestaan.")
        else:
            col1, col2 = st.columns(2)
            with col1:
                gekozen_genre = st.selectbox("Genre / Categorie:", ["Algemeen / Vrij werk", "Documentair / Straatfotografie", "Portret", "Landschap"])
                kleurtype = st.radio("Kleurtype:", ["Kleur", "Zwart-Wit"])
            with col2:
                str_intentie = st.text_input("Intentie van de foto:")
                str_context = st.text_input("Context / Omstandigheden:")
                str_techniek = st.text_input("Techniek / Nabewerking:")

            if st.button("Start Analyse", type="primary"):
                api_key = st.session_state.get("openai_api_key")
                if not api_key:
                    st.error("⚠️ Voer eerst je OpenAI API Key in de sidebar in.")
                else:
                    for f in uploaded_files:
                        with st.spinner(f"Foto '{f.name}' wordt geanalyseerd..."):
                            img_b64 = encode_image_to_base64(f)
                            rapport = genereer_individuele_analyse(api_key, img_b64, gekozen_genre, kleurtype, str_intentie, str_context, str_techniek)
                            
                            st.subheader(f"Rapport: {f.name}")
                            st.image(f, width=300)
                            st.write(rapport)

                            meta = {"Bestand": f.name, "Genre": gekozen_genre, "Kleurtype": kleurtype}
                            pdf_buf = maak_pdf_rapport(f"Juryrapport: {f.name}", meta, rapport, f)
                            st.download_button(f"Download PDF ({f.name})", data=pdf_buf, file_name=f"rapport_{f.name}.pdf", mime="application/pdf")


# -----------------------------------------------------------------------------
# 7. OPTIE 2: CURATOR EXPOSITIE SELECTIE (SCHERM_B1)
# -----------------------------------------------------------------------------
if st.session_state["huidig_scherm"] == "SCHERM_B1":
    st.header("Optie 2: Curator Expositie Selectie")
    uploaded_files = st.file_uploader("Kies 4 tot 20 foto's (Je kunt achteraf nog foto's toevoegen of verwijderen):", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True, key="curator_upload")

    if uploaded_files:
        aantal = st.number_input("Gewenst aantal voor wand:", min_value=1, max_value=len(uploaded_files), value=min(3, len(uploaded_files)))
        gekozen_genre = st.selectbox("Genre / Thema:", ["Algemeen / Vrij werk", "Expositie Thema"])
        str_intentie = st.text_input("Intentie van de expositie:")
        str_context = st.text_input("Context van de ruimte:")

        if st.button("Genereer Expositie Selectie", type="primary"):
            api_key = st.session_state.get("openai_api_key")
            if not api_key:
                st.error("⚠️ Voer eerst je OpenAI API Key in de sidebar in.")
            else:
                with st.spinner("De curator maakt een selectie..."):
                    rapport = genereer_curator_analyse(api_key, uploaded_files, aantal, gekozen_genre, str_intentie, str_context)
                    
                    id_to_file = {f"FOTO_{i+1}": f for i, f in enumerate(uploaded_files)}
                    sectie_1, sectie_2, sectie_3 = parse_curator_rapport(rapport)
                    
                    st.divider()
                    st.subheader("Resultaat Expositie Selectie")

                    # Sectie 1: Geselecteerde beelden
                    if sectie_1:
                        st.markdown("### 1. Geselecteerde Beelden (Wandvolgorde)")
                        for idx, (foto_id, reden) in enumerate(sectie_1, start=1):
                            target_file = id_to_file.get(foto_id)
                            col_thumb, col_info = st.columns([1, 3])
                            with col_thumb:
                                if target_file:
                                    st.image(target_file, use_container_width=True)
                            with col_info:
                                fname = target_file.name if target_file else foto_id
                                st.markdown(f"**Positie {idx} op de wand: {fname}** ({foto_id})")
                                st.write(f"**Motivatie:** {reden}")
                            st.divider()

                    # Sectie 2: Niet-geselecteerde beelden
                    if sectie_2:
                        st.markdown("### 2. Niet-geselecteerde Beelden")
                        for foto_id, reden in sectie_2:
                            target_file = id_to_file.get(foto_id)
                            col_thumb, col_info = st.columns([1, 3])
                            with col_thumb:
                                if target_file:
                                    st.image(target_file, use_container_width=True)
                            with col_info:
                                fname = target_file.name if target_file else foto_id
                                st.markdown(f"**{fname}** ({foto_id})")
                                st.write(f"**Motivatie:** {reden}")
                            st.divider()

                    # Sectie 3: Overkoepelend Oordeel
                    if sectie_3:
                        st.markdown("### 3. Overkoepelend Oordeel Curator")
                        st.write(sectie_3.replace("SECTIE 3: OVERKOEPELEND OORDEEL", "").strip())

                    meta = {"Totaal geüpload": len(uploaded_files), "Geselecteerd": aantal, "Genre": gekozen_genre}
                    pdf_buf = maak_curator_pdf_rapport("F-Art Curator Expositie Rapport", meta, sectie_1, sectie_2, sectie_3, id_to_file)
                    st.download_button("Download Curator Rapport als PDF", data=pdf_buf, file_name="curator_rapport.pdf", mime="application/pdf")


# -----------------------------------------------------------------------------
# 8. OPTIE 3: REEKS-ANALYSE (SCHERM_B2)
# -----------------------------------------------------------------------------
if st.session_state["huidig_scherm"] == "SCHERM_B2":
    st.header("Optie 3: Reeks-Analyse & Verhaallijn")
    st.write("Upload 4 tot maximaal 20 foto's om de onderlinge samenhang en verhaallijn te laten beoordelen.")

    uploaded_files = st.file_uploader("Kies 4 tot 20 foto's voor de reeks (Je kunt achteraf nog foto's toevoegen of verwijderen):", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True, key="reeks_upload")

    if uploaded_files:
        st.subheader("Reeks Parameters")
        col1, col2 = st.columns(2)
        with col1:
            gekozen_genre = st.selectbox("Genre / Thema van de reeks:", ["Documentair", "Storytelling", "Conceptueel", "Vrij werk"], key="reeks_genre")
            str_intentie = st.text_input("Intentie van de reeks:", key="reeks_intentie")
        with col2:
            str_context = st.text_input("Context / Achtergrondverhaal:", key="reeks_context")

        if st.button("🚀 Start Reeks-Analyse", type="primary"):
            api_key = st.session_state.get("openai_api_key")
            if not api_key:
                st.error("⚠️ Voer eerst je OpenAI API Key in de sidebar in.")
            else:
                with st.spinner("Reeks wordt geanalyseerd door de AI..."):
                    b64_list = [encode_image_to_base64(f) for f in uploaded_files]
                    names = [f.name for f in uploaded_files]
                    rapport = genereer_reeks_analyse(api_key, b64_list, names, gekozen_genre, str_intentie, str_context)

                    st.subheader(" Resultaat Reeks-Analyse")
                    st.write(rapport)

                    meta = {
                        "Aantal foto's": len(uploaded_files),
                        "Genre": gekozen_genre,
                        "Intentie": str_intentie if str_intentie else "Niet opgegeven",
                    }
                    pdf_buf = maak_reeks_pdf_rapport("F-Art Fotoclub - Reeks-Analyse Rapport", meta, rapport, uploaded_files)
                    st.download_button("Download Reeks-Rapport als PDF", data=pdf_buf, file_name="reeks_analyse_rapport.pdf", mime="application/pdf")