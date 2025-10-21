import os
import time
import requests
import json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from flask import Flask, request, jsonify

class VoterInfoBot:
    def __init__(self):
        self.driver = None
        self.two_captcha_api_key = os.environ.get('TWO_CAPTCHA_API_KEY', '6a618c70ab1c170d5ee4706d077cfbda')
        self.website_url = "https://www.elections.org.za/pw/Voter/Voter-Information"
        
    def setup_driver(self):
        """Setup Chrome driver for deployment"""
        chrome_options = Options()
        
        # Essential options for deployment
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--remote-debugging-port=9222")
        chrome_options.add_argument("--window-size=1200,800")
        
        # Anti-detection options
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        # Set Chrome binary location
        chrome_options.binary_location = os.environ.get('CHROME_PATH', '/usr/bin/google-chrome')
        
        try:
            # Try to use ChromeDriver from environment or default location
            chrome_driver_path = os.environ.get('CHROMEDRIVER_PATH', '/usr/local/bin/chromedriver')
            
            if os.path.exists(chrome_driver_path):
                service = Service(executable_path=chrome_driver_path)
                self.driver = webdriver.Chrome(service=service, options=chrome_options)
            else:
                # Let Selenium manage the driver
                self.driver = webdriver.Chrome(options=chrome_options)
                
        except Exception as e:
            print(f"ChromeDriver setup failed: {e}")
            # Final fallback
            try:
                self.driver = webdriver.Chrome(options=chrome_options)
            except Exception as final_error:
                print(f"Final driver setup failed: {final_error}")
                raise
        
        # Remove automation indicators
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        return self.driver

    def solve_recaptcha_v2(self, site_key, page_url):
        """Solve reCAPTCHA v2 using 2Captcha service"""
        print("Submitting captcha to 2captcha...")
        
        captcha_data = {
            'key': self.two_captcha_api_key,
            'method': 'userrecaptcha',
            'googlekey': site_key,
            'pageurl': page_url,
            'json': 1
        }
        
        try:
            response = requests.post('http://2captcha.com/in.php', data=captcha_data, timeout=30)
            result = response.json()
            
            if result['status'] != 1:
                raise Exception(f"Failed to submit captcha: {result.get('error_text', 'Unknown error')}")
            
            captcha_id = result['request']
            print(f"Captcha submitted successfully. ID: {captcha_id}")
            
            # Wait for solution
            for i in range(60):
                time.sleep(5)
                result_response = requests.get(
                    f'http://2captcha.com/res.php?key={self.two_captcha_api_key}&action=get&id={captcha_id}&json=1',
                    timeout=30
                )
                result_data = result_response.json()
                
                if result_data['status'] == 1:
                    print("Captcha solved successfully!")
                    return result_data['request']
                elif result_data['request'] != 'CAPCHA_NOT_READY':
                    raise Exception(f"Captcha solving failed: {result_data.get('error_text', 'Unknown error')}")
                
                if i % 5 == 0:
                    print(f"Waiting for captcha... ({i*5} seconds)")
            
            raise Exception("Captcha solving timeout")
            
        except Exception as e:
            raise Exception(f"Captcha service error: {str(e)}")
    
    def find_recaptcha_elements(self):
        """Find reCAPTCHA elements"""
        try:
            # Look for data-sitekey attribute
            recaptcha_divs = self.driver.find_elements(By.CSS_SELECTOR, "div[data-sitekey]")
            for div in recaptcha_divs:
                site_key = div.get_attribute('data-sitekey')
                if site_key and len(site_key) > 10:
                    print(f"Found reCAPTCHA site key: {site_key}")
                    return site_key
        except Exception as e:
            print(f"Data-sitekey method failed: {e}")
        
        raise Exception("Could not find reCAPTCHA elements")
    
    def inject_recaptcha_solution(self, solution):
        """Inject the recaptcha solution"""
        print("Injecting recaptcha solution...")
        
        scripts = [
            """
            var responseElement = document.getElementById('g-recaptcha-response');
            if (responseElement) {
                responseElement.value = arguments[0];
                responseElement.innerHTML = arguments[0];
            }
            """,
            """
            var responseElement = document.getElementById('g-recaptcha-response');
            if (!responseElement) {
                responseElement = document.createElement('textarea');
                responseElement.id = 'g-recaptcha-response';
                responseElement.name = 'g-recaptcha-response';
                responseElement.style.display = 'none';
                document.body.appendChild(responseElement);
            }
            responseElement.value = arguments[0];
            """
        ]
        
        for script in scripts:
            try:
                self.driver.execute_script(script, solution)
                print("✓ Solution injected successfully")
                break
            except:
                continue
        
        time.sleep(2)
    
    def extract_voter_information(self):
        """Extract voter information from results page"""
        voter_data = {}
        
        try:
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".form-row"))
            )
            
            print("Results page loaded!")
            
            # Extract data fields
            fields = {
                "identity_number": "MainContent_uxIDNumberDataField",
                "ward": "MainContent_uxWardDataField", 
                "voting_district": "MainContent_uxVDDataField",
                "name": "MainContent_uxVSNameDataField",
                "address": "MainContent_uxVSAddressDataField",
                "voting_station": "MainContent_uxVotingStationDataField"
            }
            
            for key, field_id in fields.items():
                try:
                    voter_data[key] = self.driver.find_element(By.ID, field_id).text.strip()
                    print(f"Found {key}: {voter_data[key]}")
                except:
                    voter_data[key] = "Not found"
                    print(f"Could not find {key}")
                    
        except Exception as e:
            print(f"Error extracting information: {e}")
            voter_data["error"] = "Failed to extract voter data"
        
        return voter_data
    
    def enter_voter_info(self, id_number):
        """Enter voter ID and solve captcha"""
        try:
            print("Navigating to voter information page...")
            self.driver.get(self.website_url)
            
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            time.sleep(2)
            
            # Find and fill ID field
            id_input = None
            selectors = [
                "input#IDNumber",
                "input[name='IDNumber']", 
                "input[type='text']"
            ]
            
            for selector in selectors:
                try:
                    id_input = self.driver.find_element(By.CSS_SELECTOR, selector)
                    break
                except:
                    continue
            
            if not id_input:
                inputs = self.driver.find_elements(By.CSS_SELECTOR, "input[type='text']")
                if inputs:
                    id_input = inputs[0]
                else:
                    raise Exception("Could not find ID input field")
            
            id_input.clear()
            id_input.send_keys(id_number)
            print(f"Entered ID: {id_number}")
            
            # Solve captcha
            site_key = self.find_recaptcha_elements()
            captcha_solution = self.solve_recaptcha_v2(site_key, self.website_url)
            self.inject_recaptcha_solution(captcha_solution)
            
            # Find and click submit
            submit_selectors = [
                "input[type='submit']",
                "button[type='submit']",
                ".btn-primary"
            ]
            
            for selector in submit_selectors:
                try:
                    submit_button = self.driver.find_element(By.CSS_SELECTOR, selector)
                    submit_button.click()
                    print("Form submitted")
                    time.sleep(5)
                    return True
                except:
                    continue
            
            return False
            
        except Exception as e:
            print(f"Error during voter info entry: {str(e)}")
            return False
    
    def get_voter_information(self, id_number):
        """Main method to get voter information"""
        try:
            self.setup_driver()
            success = self.enter_voter_info(id_number)
            
            if success and "My-ID-Information-Details" in self.driver.current_url:
                print("Successfully reached results page!")
                voter_data = self.extract_voter_information()
                return voter_data
            else:
                return {"error": "Failed to retrieve voter information"}
                
        except Exception as e:
            return {"error": f"Bot execution failed: {str(e)}"}
        finally:
            if self.driver:
                try:
                    self.driver.quit()
                except:
                    pass

# Flask app
app = Flask(__name__)

@app.route('/')
def serve_html():
    try:
        with open('ConnectVoterDrive.html', 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return "HTML file not found", 404

@app.route('/verify_voter', methods=['POST'])
def verify_voter():
    data = request.get_json(silent=True)
    
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400
        
    id_number = data.get('id_number')
    
    if not id_number or len(id_number) != 13 or not id_number.isdigit():
        return jsonify({"error": "Invalid ID number"}), 400
    
    print(f"Processing ID: {id_number}")
    
    try:
        bot = VoterInfoBot()
        voter_data = bot.get_voter_information(id_number)
        
        if "error" in voter_data:
            return jsonify({"error": voter_data["error"]}), 500
        
        response_data = {
            "success": True,
            "fullName": voter_data.get("name", "Not found"),
            "age": calculate_age_from_id(id_number),
            "ward": voter_data.get("ward", "Not found"),
            "votingDistrict": voter_data.get("voting_district", "Not found"),
            "votingStation": voter_data.get("voting_station", "Not found"),
            "address": voter_data.get("address", "Not found")
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        return jsonify({"error": f"Server error: {str(e)}"}), 500

def calculate_age_from_id(id_number):
    try:
        year = int(id_number[:2])
        current_year = int(time.strftime("%Y"))
        current_short_year = current_year % 100
        
        if year <= current_short_year:
            birth_year = 2000 + year
        else:
            birth_year = 1900 + year
        
        age = current_year - birth_year
        return f"{age} years"
    except:
        return "Based on ID"

def run_flask_app():
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    
    print(f"Starting server on port {port}")
    
    if debug:
        app.run(host='0.0.0.0', port=port, debug=True)
    else:
        try:
            from waitress import serve
            serve(app, host='0.0.0.0', port=port)
        except ImportError:
            app.run(host='0.0.0.0', port=port, debug=False)

def main():
    print("Voter Information Bot")
    print("1. Start Flask server")
    print("2. Command line mode")
    
    choice = input("Choose mode (1 or 2): ").strip()
    
    if choice == "1":
        run_flask_app()
    else:
        id_number = input("Enter ID number: ").strip()
        if id_number and len(id_number) == 13 and id_number.isdigit():
            bot = VoterInfoBot()
            result = bot.get_voter_information(id_number)
            print("Result:", result)
        else:
            print("Invalid ID number")

if __name__ == "__main__":
    main()