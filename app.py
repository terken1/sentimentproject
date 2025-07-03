import streamlit as st
import requests
from bs4 import BeautifulSoup
from google import genai
from config import API_KEY
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import time
import random
import os
from datetime import datetime

# Configure Gemini client
if API_KEY:
    # genai.configure(api_key=API_KEY) # Old method
    # client = genai.GenerativeModel('gemini-pro') # Old method
    try:
        client = genai.Client(api_key=API_KEY)
        # Test with a simple model list call to ensure client is working
        # model_list = [m.name for m in client.list_models()]
        # if not any('gemini-pro' in m for m in model_list):
        #     st.warning("Gemini-pro model not found. Please check your API key and model availability.")
        # We will use a specific model in analyze_sentiment_google, e.g., "gemini-1.0-pro" or "gemini-pro"
    except Exception as e:
        st.error(f"Failed to initialize Gemini client: {e}")
        st.stop()
else:
    st.error("API_KEY not found in config.py. Please add it to proceed.")
    st.stop()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7", # Prioritize Turkish
}

def save_page_source(driver, reason):
    """Saves the page source for debugging purposes."""
    if not os.path.exists("debug_html"):
        os.makedirs("debug_html")
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"debug_html/amazon_page_{reason}_{timestamp}.html"
    
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        st.warning(f"Could not find product details. Saved page HTML for debugging: {filename}")
    except Exception as e:
        st.error(f"Error saving debug HTML: {e}")

def init_selenium_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument(f"user-agent={HEADERS['User-Agent']}")
    chrome_options.add_argument(f"accept-language={HEADERS['Accept-Language']}")
    try:
        # Use webdriver_manager to automatically download and manage ChromeDriver
        driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=chrome_options)
        return driver
    except Exception as e:
        st.error(f"Error initializing Selenium WebDriver: {e}. Ensure Chrome is installed.")
        return None

def scrape_product_info_selenium(url, driver, retries=3):
    if not driver:
        return {"title": "Error", "price": "Error", "image_url": None, "error": "WebDriver not initialized", "star_rating": "N/A", "rating_count": "N/A"}

    for attempt in range(retries):
        st.info(f"Fetching product info... (Attempt {attempt + 1}/{retries})")
        try:
            driver.get(url)
            # Rastgele bir bekleme süresi, bot tespitini zorlaştırır
            time.sleep(random.uniform(2, 5)) 

            soup = BeautifulSoup(driver.page_source, "html.parser")

            # --- Başlık ---
            title_element = soup.find(id="productTitle")
            title = title_element.get_text(strip=True) if title_element else "Title not found"

            # --- Resim ---
            image_url = None
            image_selectors = [
                "img#landingImage",
                "div#imgTagWrapperId img",
                "div#main-image-container img",
                "div.imgTagWrapper img",
                "div#altImages ul li.selected img",
                # Yeni eklenen daha genel bir seçici
                ".a-dynamic-image.a-stretch-horizontal" 
            ]
            for selector in image_selectors:
                img_element = soup.select_one(selector)
                if img_element:
                    # 'src' 'data-old-hires' den daha güvenilir olabilir. Öncelik sırasını ayarla.
                    if img_element.has_attr('src') and not img_element['src'].startswith('data:image'):
                         image_url = img_element['src']
                         break
                    if img_element.has_attr('data-old-hires'):
                         image_url = img_element['data-old-hires']
                         break
            
            # --- Fiyat ---
            price = "Price not found"
            price_text_found = None
            
            # Fiyat için en güvenilir seçiciler
            price_selectors = [
                '#corePrice_desktop .a-offscreen',
                '#corePriceDisplay_desktop_feature_div .a-offscreen',
                '.priceToPay span.a-offscreen',
                'span#priceblock_ourprice', 
                'span#priceblock_dealprice', 
                'span#price_inside_buybox',
                '#apex_desktop .a-offscreen',
                'span[data-a-size="xl"] span.a-offscreen',
                'span[data-a-size="l"] span.a-offscreen',
                # Sadece fiyatın kendisini içeren daha genel yapılar
                '.a-price-whole', 
            ]

            for selector in price_selectors:
                price_element = soup.select_one(selector)
                if price_element and price_element.get_text(strip=True):
                    price_text_found = price_element.get_text(strip=True)
                    break
            
            # Fiyat bulunduysa temizle ve formatla
            if price_text_found:
                # Bazen "Ücretsiz" gibi metinler gelebilir, bunları koru
                if not any(char.isdigit() for char in price_text_found):
                     price = price_text_found.strip()
                # Para birimi ve sayı içeren standart fiyatlar
                elif "amazon.com.tr" in url:
                    # TL formatlaması
                    clean_price = ''.join(filter(lambda x: x.isdigit() or x in ',', price_text_found))
                    price = f"{clean_price} TL"
                elif "amazon.com" in url:
                    # Dolar formatlaması
                    clean_price = ''.join(filter(lambda x: x.isdigit() or x in '.', price_text_found))
                    price = f"${clean_price}"
                else:
                    price = price_text_found.strip()

            # --- Yıldız ve Yorum Sayısı ---
            star_rating = "Rating not found"
            rating_count = "Count not found"
            try:
                # Yıldız Puanı (Örn: "5 üzerinden 4,5 yıldız")
                star_element = soup.select_one("#acrPopover .a-icon-alt")
                if star_element:
                    star_rating = star_element.get_text(strip=True)
                # Yorum Sayısı (Örn: "1.234 değerlendirme")
                rating_count_element = soup.select_one("#acrCustomerReviewText")
                if rating_count_element:
                    rating_count = rating_count_element.get_text(strip=True)
            except Exception:
                # Bu alanlar kritik değil, bulunamazsa geç
                pass

            # --- Kontrol ve Tekrar Deneme ---
            if title != "Title not found" and price != "Price not found":
                st.success("Successfully fetched product details!")
                return {"title": title, "price": price, "image_url": image_url, "star_rating": star_rating, "rating_count": rating_count}
            else:
                # Başarısızlık durumunda loglama
                if title == "Title not found":
                    st.warning("Title could not be found.")
                    save_page_source(driver, "title_not_found")
                if price == "Price not found":
                    st.warning("Price could not be found.")
                    save_page_source(driver, "price_not_found")
            
            # Son deneme değilse, bir sonraki deneme için bekle
            if attempt < retries - 1:
                 st.info(f"Retrying after a short delay...")
                 time.sleep(random.uniform(3, 7))

        except requests.exceptions.RequestException as e:
            st.error(f"Network error on attempt {attempt + 1}: {e}")
            if attempt >= retries - 1:
                 return {"title": "Error", "price": "Error", "image_url": None, "error": str(e), "star_rating": "N/A", "rating_count": "N/A"}

        except Exception as e:
            st.error(f"An error occurred on attempt {attempt + 1}: {e}")
            save_page_source(driver, "exception")
            # Beklenmedik bir hata olursa döngüyü kır
            if attempt >= retries - 1:
                return {"title": "Error", "price": "Error", "image_url": None, "error": str(e), "star_rating": "N/A", "rating_count": "N/A"}

    # Tüm denemeler başarısız olursa
    st.error("Failed to fetch product info after all retries.")
    return {"title": "Title not found", "price": "Price not found", "image_url": None, "error": "All retries failed", "star_rating": "N/A", "rating_count": "N/A"}

def fetch_reviews_selenium(url, driver):
    if not driver:
        return []
    try:
        driver.get(url) # Re-navigate or ensure page is current if different from product info
        time.sleep(3) # Wait for dynamic content

        # Scroll down to trigger loading of more reviews if they are lazy-loaded
        # for _ in range(3): # Scroll a few times
        # driver.execute_script("window.scrollTo(0, document.body.scrollHeight);"))
        #    time.sleep(1)
            
        soup = BeautifulSoup(driver.page_source, "html.parser")
        
        review_elements = []
        # Try multiple selectors, as page structures can vary
        selectors = [
            "span[data-hook='review-body']",
            "div.review-text-content > span", # More general
            "div.a-expander-content.reviewText.review-text-content > span",
            "div[data-hook='review-collapsed']" # Sometimes reviews are collapsed
        ]
        
        for selector in selectors:
            elements = soup.select(selector)
            if elements:
                review_elements.extend(elements)
                # If one selector works well, you might break, or collect from all

        reviews = list(set([review.get_text(strip=True) for review in review_elements])) # Use set to remove duplicates

        if not reviews:
            st.warning("No reviews found with Selenium. The page structure might be too different, or reviews require specific interaction (e.g., clicking a button) not yet implemented.")
        return reviews
    except Exception as e:
        st.error(f"Error fetching reviews with Selenium: {e}")
        return []

def analyze_sentiment_google(review_text):
    if not API_KEY:
        return "API Key not configured"
    try:
        # Güncellenmiş prompt: Çeşitli pozitif emojiler istiyoruz
        prompt = f"Bu ürün yorumunu değerlendir. Yorumun dilini de tahmin et (örneğin, Türkçe, İngilizce). Cevabın MUTLAKA ŞU FORMATTA OLSUN: [EMOJİ] - [DİL] - ([KISA AÇIKLAMA]). EMOJİ sadece yüz ifadeleri gibi duygu belirten bir emoji olmalı (el hareketleri, parmak işaretleri KULLANMA). Eğer duygu olumluysa, lütfen şu emojilerden rastgele birini veya benzerlerini kullan: 😊, 😄, 😀, 😍, 😎, 🥳, 🤩,🤠. Olumsuz veya nötr durumlar için uygun farklı bir yüz ifadesi emojisi kullan. Örnek: 🤩 - Türkçe - (kesinlikle tavsiye ederim!). Yorum: '{review_text}'"

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        
        if response.text:
             return response.text.strip()
        else:
            # Yanıtın tamamını loglayarak ne geldiğini görebiliriz (isteğe bağlı)
            # st.write("Unexpected API response:", response)
            return "Could not parse sentiment (empty response text)"
            
    except Exception as e:
        # Hata mesajında API'den gelen spesifik detayları göstermeye çalışalım
        error_message = f"Error during sentiment analysis: {e}"
        if hasattr(e, 'message') and "RESOURCE_EXHAUSTED" in str(e.message):
            error_message += "\n\n**Gemini API Hız Sınırı Aşıldı.** Lütfen bir süre bekleyip tekrar deneyin veya Google Cloud Console üzerinden kotanızı kontrol edin."
        st.error(error_message)
        return "Error"

# --- Streamlit UI ---
st.set_page_config(layout="wide", page_title="Amazon Product Analyzer")

# Custom CSS to increase expander font size
st.markdown("""
<style>
/* A more general and forceful selector for expander titles */
summary {
    font-size: 22px !important;
}
</style>
""", unsafe_allow_html=True)

st.title("📦 Amazon Product Analyzer")

st.sidebar.header("About")
st.sidebar.info(
    "Bu proje Konya Gıda ve Tarım Üniversitesi öğrencileri tarafından geliştirilmiştir. "
)

product_url = st.text_input("Enter Amazon Product Link:", placeholder="https://www.amazon.com/dp/...")

if st.button("Analyze Product"):
    if not product_url or not (product_url.startswith("https://www.amazon.") or product_url.startswith("https://amazon.")):
        st.error("Please enter a valid Amazon product link.")
    else:
        # Selenium driver'ını başlat
        with st.spinner("Initializing WebDriver..."):
            driver = init_selenium_driver()

        if driver:
            try:
                # Ürün Bilgilerini Çek
                with st.spinner("Fetching product information... This may take a moment."):
                    product_info = scrape_product_info_selenium(product_url, driver)

                if product_info.get("error"):
                    st.error(f"Failed to retrieve product information: {product_info['error']}")
                elif product_info["title"] == "Title not found":
                    st.error("Could not retrieve product details. The page layout may have changed or it might be a captcha page. Check the saved debug HTML file if one was created.")
                else:
                    # Ürün bilgilerini göster
                    st.header("Product Information")
                    col1, col2 = st.columns([1, 2])
                    with col1:
                        if product_info["image_url"]:
                            st.image(product_info["image_url"], width=250)
                        else:
                            st.warning("No image found.")
                    with col2:
                        st.subheader(product_info["title"])
                        st.markdown(f"**Price:** `{product_info['price']}`")
                        if product_info.get("star_rating") and "not found" not in product_info["star_rating"].lower():
                            st.markdown(f"**Rating:** {product_info['star_rating']}")
                        if product_info.get("rating_count") and "not found" not in product_info["rating_count"].lower():
                            st.markdown(f"**Total Ratings:** {product_info['rating_count']}")
                    
                    st.markdown("---")

                    # Yorumları Çek
                    with st.spinner("Fetching reviews..."):
                        reviews_all = fetch_reviews_selenium(product_url, driver)
                    
                    # Rastgele 10 yorum seç (veya daha azsa hepsi)
                    if reviews_all and len(reviews_all) > 10:
                        reviews = random.sample(reviews_all, 10)
                        st.info(f" Analyzing a random sample of {len(reviews)} reviews.")
                    else:
                        reviews = reviews_all

                    # Yorumları Analiz Et
                    if reviews:
                        st.header(f"Sentiment Analysis of {len(reviews)} Reviews")
                        results = []
                        progress_bar = st.progress(0)
                        status_text = st.empty()

                        for i, review_text in enumerate(reviews):
                            status_text.text(f"Analyzing review {i+1}/{len(reviews)}...")
                            sentiment = analyze_sentiment_google(review_text)
                            results.append({"review": review_text, "sentiment": sentiment})
                            progress_bar.progress((i + 1) / len(reviews))
                            # API hız sınırını aşmamak için küçük bir bekleme
                            time.sleep(1) 
                        
                        status_text.text("Analysis complete!")

                        for i, result in enumerate(results):
                            # Hata durumunda başlığı farklı göster
                            expander_title = f"Review #{i+1} | Sentiment: {result['sentiment']}"
                            if "Error" in result['sentiment']:
                                expander_title = f"⚠️ Review #{i+1} | {result['sentiment']}"
                            
                            with st.expander(expander_title):
                                st.markdown(f"**Review:**\n> {result['review']}")

                    elif reviews_all is not None: # fetch_reviews_selenium'dan boş liste geldiyse
                        st.warning("No reviews were found for this product.")

            finally:
                 # Her zaman driver'ı kapat
                driver.quit()

st.sidebar.markdown("---")
st.sidebar.markdown("Powered by Streamlit & Gemini") 