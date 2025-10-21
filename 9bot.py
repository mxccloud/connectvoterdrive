import os
import time
import requests
import json
import subprocess
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
        """Environment-aware Chrome driver setup"""
        chrome_options = Options()
        
        # Essential options for headless environments
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1200,800")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        # Additional stability options
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-plugins")
        chrome_options.add_argument("--disable-images")
        chrome_options.add_argument("--disable-javascript")
        chrome_options.add_argument("--log-level=3")
        
        print("Checking Chrome availability...")
        
        try:
            # Method 1: Try system Chrome first (Render's default)
            print("Attempting to use system Chrome...")
            self.driver = webdriver.Chrome(options=chrome_options)
            print("✓ System Chrome setup successful")
            
        except Exception as e:
            print(f"System Chrome failed: {e}")
            
            # Method 2: Try ChromeDriver Manager as fallback
            try:
                print("Trying ChromeDriver Manager...")
                from webdriver_manager.chrome import ChromeDriverManager
                
                service = Service(ChromeDriverManager().install())
                self.driver = webdriver.Chrome(service=service, options=chrome_options)
                print("✓ ChromeDriver Manager setup successful")
                
            except Exception as manager_error:
                print(f"ChromeDriver Manager failed: {manager_error}")
                
                # Method 3: Try with explicit service
                try:
                    print("Trying explicit service...")
                    service = Service()
                    self.driver = webdriver.Chrome(service=service, options=chrome_options)
                    print("✓ Explicit service setup successful")
                except Exception as service_error:
                    print(f"Explicit service failed: {service_error}")
                    
                    # Method 4: Final fallback - let Selenium handle everything
                    try:
                        print("Trying final fallback...")
                        self.driver = webdriver.Chrome(options=chrome_options)
                        print("✓ Final fallback setup successful")
                    except Exception as final_error:
                        print(f"All driver setup methods failed: {final_error}")
                        raise Exception(f"Could not initialize ChromeDriver: {str(final_error)}")
        
        # Additional anti-detection measures
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        self.driver.execute_cdp_cmd('Network.setUserAgentOverride', {
            "userAgent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        
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
            var iframes = document.getElementsByTagName('iframe');
            for (var i = 0; i < iframes.length; i++) {
                var iframe = iframes[i];
                try {
                    var iframeDoc = iframe.contentDocument || iframe.contentWindow.document;
                    var responseElement = iframeDoc.getElementById('g-recaptcha-response');
                    if (responseElement) {
                        responseElement.value = arguments[0];
                    }
                } catch(e) {}
            }
            """
        ]
        
        for script in scripts:
            try:
                self.driver.execute_script(script, solution)
                print("✓ Solution injected successfully")
                break
            except Exception as e:
                print(f"Script injection failed: {e}")
                continue
        
        time.sleep(2)
    
    def extract_voter_information(self):
        """Extract voter information from results page"""
        voter_data = {}
        
        try:
            # Wait for results page to load
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".form-row, .form-group, input, div"))
            )
            
            print("Results page loaded!")
            
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
                    element = self.driver.find_element(By.ID, field_id)
                    voter_data[key] = element.text.strip()
                    print(f"Found {key}: {voter_data[key]}")
                except Exception as e:
                    voter_data[key] = "Not found"
                    print(f"Could not find {key}: {e}")
            
            # Alternative extraction methods if primary fails
            if all(value == "Not found" for value in voter_data.values()):
                print("Trying alternative extraction methods...")
                try:
                    # Look for any text content that might contain voter info
                    body_text = self.driver.find_element(By.TAG_NAME, "body").text
                    lines = body_text.split('\n')
                    for line in lines:
                        if 'name' in line.lower() and voter_data['name'] == "Not found":
                            voter_data['name'] = line.strip()
                        elif 'ward' in line.lower() and voter_data['ward'] == "Not found":
                            voter_data['ward'] = line.strip()
                        elif 'station' in line.lower() and voter_data['voting_station'] == "Not found":
                            voter_data['voting_station'] = line.strip()
                except Exception as e:
                    print(f"Alternative extraction failed: {e}")
                    
        except Exception as e:
            print(f"Error extracting information: {e}")
            voter_data["error"] = f"Failed to extract voter data: {str(e)}"
        
        return voter_data
    
    def enter_voter_info(self, id_number):
        """Enter voter ID and solve captcha"""
        try:
            print("Navigating to voter information page...")
            self.driver.get(self.website_url)
            
            # Wait for page to load
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            time.sleep(3)
            
            # Find and fill ID field
            id_input = None
            selectors = [
                "input#IDNumber",
                "input[name='IDNumber']", 
                "input[type='text']",
                "input[placeholder*='ID']",
                "input[placeholder*='id']"
            ]
            
            for selector in selectors:
                try:
                    id_input = self.driver.find_element(By.CSS_SELECTOR, selector)
                    if id_input.is_displayed() and id_input.is_enabled():
                        break
                except:
                    continue
            
            if not id_input:
                # Try to find any text input
                inputs = self.driver.find_elements(By.CSS_SELECTOR, "input[type='text']")
                for input_field in inputs:
                    if input_field.is_displayed() and input_field.is_enabled():
                        id_input = input_field
                        break
            
            if not id_input:
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
                ".btn-primary",
                ".btn",
                "button",
                "input[value*='Submit']",
                "input[value*='submit']"
            ]
            
            for selector in submit_selectors:
                try:
                    submit_button = self.driver.find_element(By.CSS_SELECTOR, selector)
                    if submit_button.is_displayed() and submit_button.is_enabled():
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
            
            if success:
                print("Checking if we reached results page...")
                print(f"Current URL: {self.driver.current_url}")
                
                # Check various success indicators
                success_indicators = [
                    "My-ID-Information-Details" in self.driver.current_url,
                    "details" in self.driver.current_url.lower(),
                    "information" in self.driver.current_url.lower()
                ]
                
                if any(success_indicators):
                    print("Successfully reached results page!")
                    voter_data = self.extract_voter_information()
                    return voter_data
                else:
                    # Take screenshot for debugging
                    try:
                        screenshot_path = f"/tmp/error_{id_number}.png"
                        self.driver.save_screenshot(screenshot_path)
                        print(f"Screenshot saved to: {screenshot_path}")
                    except:
                        print("Could not save screenshot")
                    
                    return {"error": "Failed to reach results page after submission"}
            else:
                return {"error": "Failed to submit voter information"}
                
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
        print(f"Server error: {str(e)}")
        return jsonify({"error": f"Server configuration error: {str(e)}"}), 500

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

def check_chrome_availability():
    """Check if Chrome is available in the system"""
    try:
        # Check for Chrome
        result = subprocess.run(['which', 'google-chrome'], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✓ Chrome found at: {result.stdout.strip()}")
        else:
            print("✗ Chrome not found in PATH")
        
        # Check for chromedriver
        result = subprocess.run(['which', 'chromedriver'], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✓ ChromeDriver found at: {result.stdout.strip()}")
        else:
            print("✗ ChromeDriver not found in PATH")
            
    except Exception as e:
        print(f"Chrome availability check failed: {e}")

def run_flask_app():
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    
    print("=" * 50)
    print("Voter Information Bot - Render Deployment")
    print("=" * 50)
    
    # Check system dependencies
    check_chrome_availability()
    
    print(f"Starting server on port {port}")
    print(f"Debug mode: {debug}")
    
    if debug:
        app.run(host='0.0.0.0', port=port, debug=True)
    else:
        try:
            from waitress import serve
            print("Using Waitress production server")
            serve(app, host='0.0.0.0', port=port)
        except ImportError:
            print("Waitress not available, using Flask development server")
            app.run(host='0.0.0.0', port=port, debug=False)

def main():
    print("Voter Information Bot - Render Deployment")
    print("Starting Flask server automatically for Render...")
    run_flask_app()

if __name__ == "__main__":
    main()
