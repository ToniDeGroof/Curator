import io
import json
import base64
from PIL import Image
from supabase import create_client, Client
import openai

# ---------------------------------------------------------------------------
# SUPABASE CONFIGURATIE
# ---------------------------------------------------------------------------
SUPABASE_URL = "https://nnccxqwzwjdrueafiukl.supabase.co"
SUPABASE_KEY = "sb_publishable_JtTk0EoTWsfOyIqbWet1xA_rHtpfqzq"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------------------------------------------------------------------
# HULPFUNCTIES
# ---------------------------------------------------------------------------
def compress_image(image_bytes, max_size=(1080, 1080), quality=85):
    """Verkleint de afbeelding voor snelle upload en lage opslagkosten."""
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode != 'RGB':
        img = img.convert('RGB')
    img.thumbnail(max_size, Image.Resampling.LANCZOS)
    
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()

def upload_to_supabase_storage(file_bytes, filename, bucket="fotos"):
    """Uploadt de afbeelding naar Supabase Storage en geeft de publieke URL terug."""
    path_on_supa = f"academie/{filename}"
    compressed_bytes = compress_image(file_bytes)
    
    supabase.storage.from_(bucket).upload(
        path=path_on_supa,
        file=compressed_bytes,
        file_options={"content-type": "image/jpeg", "x-upsert": "true"}
    )
    
    public_url = supabase.storage.from_(bucket).get_public_url(path_on_supa)
    return public_url

def analyze_photo_with_ai(image_bytes, api_key, titel, locatie, tag):
    """Analyseert de foto via GPT-4o en genereert de beoordeling + 5 reflectievragen."""
    client = openai.OpenAI(api_key=api_key)
    base64_image = base64.b64encode(compress_image(image_bytes, max_size=(800, 800))).decode('utf-8')
    
    prompt = f"""
    Je bent een kritische en opbouwende docent fotografie aan een Kunstacademie. 
    Analyseer de bijgevoegde foto. 
    Context:
    - Titel: {titel}
    - Locatie: {locatie}
    - Categorie/Tag: {tag}

    Geef je antwoord UITSLUITEND terug in valide JSON met de volgende exacte structuur:
    {{
        "totaal_score": 82,
        "scores": {{
            "Compositie": 8,
            "Lichtinval": 8,
            "Scherpte_Techniek": 7,
            "Sfeer_Impact": 9,
            "Narratief_Concept": 8
        }},
        "jurytekst": "Korte inhoudelijke onderbouwing/analyse (max 150 woorden)...",
        "reflectie_vragen": [
            "Vraag 1 over compositie/kadering?",
            "Vraag 2 over het effect van licht/donker?",
            "Vraag 3 over timing of het beslissende moment?",
            "Vraag 4 over de sfeer of boodschap?",
            "Vraag 5 over een eventuele bewerking of uitsnede?"
        ]
    }}
    """
    
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
                    }
                ]
            }
        ],
        response_format={"type": "json_object"},
        temperature=0.7
    )
    
    return json.loads(response.choices[0].message.content)

def save_beoordeling_to_db(titel, locatie, jaar, maand, tag, image_url, ai_result):
    """Slaat de foto-metadata en AI-analyse op in de Supabase Database."""
    data = {
        "titel": titel,
        "locatie": locatie,
        "jaar": int(jaar),
        "maand": maand,
        "tag": tag,
        "image_url": image_url,
        "scores": ai_result.get("scores"),
        "totaal_score": ai_result.get("totaal_score"),
        "jurytekst": ai_result.get("jurytekst"),
        "reflectie_vragen": ai_result.get("reflectie_vragen")
    }
    
    response = supabase.table("beoordelingen").insert(data).execute()
    return response.data

def get_all_beoordelingen():
    """Haalt alle opgeslagen beoordelingen op uit de database, nieuwste eerst."""
    response = supabase.table("beoordelingen").select("*").order("created_at", desc=True).execute()
    return response.data