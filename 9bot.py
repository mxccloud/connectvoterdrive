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
import threading
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

class VoterInfoBot:
    def __init__(self):
        self.driver = None
        # Use environment variable for API key with fallback for local development
        self.two_captcha_api_key = os.environ.get('TWO_CAPTCHA_API_KEY', '6a618c70ab1c170d5ee4706d077cfbda')
        self.website_url = "https://www.elections.org.za/pw/Voter/Voter-Information"
        self.results_url = "https://www.elections.org.za/pw/Voter/My-ID-Information-Details"
        
    def setup_driver(self):
        """Setup Chrome driver with appropriate options for deployment"""
        chrome_options = Options()
        
        # Deployment-specific options
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--remote-debugging-port=9222")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        chrome_options.add_argument("--window-size=1200,800")
        
        # For deployment environments
        if os.environ.get('CHROME_PATH'):
            chrome_options.binary_location = os.environ.get('CHROME_PATH')
        
        # Set up driver based on environment
        try:
            # Try different possible ChromeDriver locations for various platforms
            possible_paths = [
                '/app/.chromedriver/bin/chromedriver',  # Railway
                '/usr/local/bin/chromedriver',          # Heroku
                '/usr/bin/chromedriver',                # Linux systems
                'chromedriver',                         # Local development
                './chromedriver'                        # Current directory
            ]
            
            driver_path = None
            for path in possible_paths:
                if os.path.exists(path):
                    driver_path = path
                    print(f"Found ChromeDriver at: {path}")
                    break
            
            if driver_path:
                service = Service(executable_path=driver_path)
                self.driver = webdriver.Chrome(service=service, options=chrome_options)
            else:
                # Let Selenium manage the driver automatically
                self.driver = webdriver.Chrome(options=chrome_options)
                
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            return self.driver
            
        except Exception as e:
            print(f"Error setting up Chrome driver: {e}")
            # Fallback: try without specifying path
            try:
                self.driver = webdriver.Chrome(options=chrome_options)
                self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
                return self.driver
            except Exception as fallback_error:
                print(f"Fallback driver setup also failed: {fallback_error}")
                raise
    
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
            
            # Wait for captcha to be solved
            print("Waiting for captcha solution... (this can take 10-60 seconds)")
            for i in range(60):
                time.sleep(5)
                result_response = requests.get(
                    f'http://2captcha.com/res.php?key={self.two_captcha_api_key}'
                    f'&action=get&id={captcha_id}&json=1',
                    timeout=30
                )
                result_data = result_response.json()
                
                if result_data['status'] == 1:
                    print("Captcha solved successfully!")
                    return result_data['request']
                elif result_data['request'] != 'CAPCHA_NOT_READY':
                    raise Exception(f"Captcha solving failed: {result_data.get('error_text', 'Unknown error')}")
                
                if i % 5 == 0:
                    print(f"Still waiting... ({i*5} seconds)")
            
            raise Exception("Captcha solving timeout (5 minutes)")
            
        except requests.exceptions.Timeout:
            raise Exception("Captcha service timeout - please try again")
        except requests.exceptions.RequestException as e:
            raise Exception(f"Network error contacting captcha service: {str(e)}")
    
    def find_recaptcha_elements(self):
        """Find reCAPTCHA elements and return site key"""
        try:
            # Method 1: Look for data-sitekey attribute
            recaptcha_divs = self.driver.find_elements(By.CSS_SELECTOR, "div[data-sitekey]")
            for div in recaptcha_divs:
                site_key = div.get_attribute('data-sitekey')
                if site_key and len(site_key) > 10:
                    print(f"Found reCAPTCHA site key: {site_key}")
                    return site_key
        except Exception as e:
            print(f"Data-sitekey method failed: {e}")
        
        try:
            # Method 2: Look for iframe with recaptcha
            recaptcha_iframes = self.driver.find_elements(By.CSS_SELECTOR, "iframe[src*='google.com/recaptcha']")
            for iframe in recaptcha_iframes:
                src = iframe.get_attribute('src')
                if 'recaptcha' in src:
                    import re
                    site_key_match = re.search(r'k=([^&]+)', src)
                    if site_key_match:
                        site_key = site_key_match.group(1)
                        print(f"Found reCAPTCHA site key from iframe: {site_key}")
                        return site_key
        except Exception as e:
            print(f"Iframe method failed: {e}")
            
        raise Exception("Could not find reCAPTCHA elements on the page")
    
    def inject_recaptcha_solution(self, solution):
        """Inject the recaptcha solution properly"""
        print("Injecting recaptcha solution...")
        
        # Multiple methods to inject the solution
        scripts = [
            # Method 1: Set g-recaptcha-response textarea
            """
            var responseElement = document.getElementById('g-recaptcha-response');
            if (responseElement) {
                responseElement.innerHTML = arguments[0];
            }
            """,
            
            # Method 2: Set the value attribute
            """
            var responseElement = document.getElementById('g-recaptcha-response');
            if (responseElement) {
                responseElement.value = arguments[0];
            }
            """,
            
            # Method 3: Create element if it doesn't exist
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
            responseElement.innerHTML = arguments[0];
            """,
            
            # Method 4: Dispatch events to trigger validation
            """
            var responseElement = document.getElementById('g-recaptcha-response');
            if (responseElement) {
                responseElement.value = arguments[0];
                responseElement.innerHTML = arguments[0];
                
                // Trigger events
                var event = new Event('change', { bubbles: true });
                responseElement.dispatchEvent(event);
                
                var inputEvent = new Event('input', { bubbles: true });
                responseElement.dispatchEvent(inputEvent);
            }
            """
        ]
        
        for i, script in enumerate(scripts):
            try:
                self.driver.execute_script(script, solution)
                print(f"Successfully injected solution with method {i+1}")
                break
            except Exception as e:
                print(f"Method {i+1} failed: {e}")
                continue
        
        # Additional wait and verification
        time.sleep(3)
        
        # Verify the solution was injected
        try:
            response_element = self.driver.find_element(By.ID, "g-recaptcha-response")
            injected_value = self.driver.execute_script("return arguments[0].value", response_element)
            if injected_value == solution:
                print("✓ Recaptcha solution verified successfully!")
            else:
                print("⚠ Recaptcha solution may not have been set properly")
        except:
            print("⚠ Could not verify recaptcha solution injection")
    
    def extract_voter_information(self):
        """Extract voter information from the results page"""
        print("Extracting voter information from results page...")
        
        voter_data = {}
        
        try:
            # Wait for the results page to load
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".form-row"))
            )
            
            print("Results page loaded successfully!")
            
            # Extract data from the first form-row section
            try:
                voter_data["identity_number"] = self.driver.find_element(By.ID, "MainContent_uxIDNumberDataField").text.strip()
                print(f"Found ID: {voter_data['identity_number']}")
            except:
                voter_data["identity_number"] = "Not found"
                print("Could not find identity number")
                
            try:
                voter_data["ward"] = self.driver.find_element(By.ID, "MainContent_uxWardDataField").text.strip()
                print(f"Found ward: {voter_data['ward']}")
            except:
                voter_data["ward"] = "Not found"
                print("Could not find ward")
                
            try:
                voter_data["voting_district"] = self.driver.find_element(By.ID, "MainContent_uxVDDataField").text.strip()
                print(f"Found voting district: {voter_data['voting_district']}")
            except:
                voter_data["voting_district"] = "Not found"
                print("Could not find voting district")
            
            # Extract data from the second form-row section
            try:
                voter_data["name"] = self.driver.find_element(By.ID, "MainContent_uxVSNameDataField").text.strip()
                print(f"Found name: {voter_data['name']}")
            except:
                voter_data["name"] = "Not found"
                print("Could not find name")
                
            try:
                voter_data["address"] = self.driver.find_element(By.ID, "MainContent_uxVSAddressDataField").text.strip()
                # Clean up address formatting
                voter_data["address"] = ' '.join(voter_data["address"].split())
                print(f"Found address: {voter_data['address']}")
            except:
                voter_data["address"] = "Not found"
                print("Could not find address")
                
            # Extract voting station information
            try:
                voter_data["voting_station"] = self.driver.find_element(By.ID, "MainContent_uxVotingStationDataField").text.strip()
                print(f"Found voting station: {voter_data['voting_station']}")
            except:
                # If specific voting station element not found, use address
                voter_data["voting_station"] = voter_data.get("address", "Not found")
                print("Using address as voting station")
                    
        except Exception as e:
            print(f"Error extracting voter information: {e}")
            # Save page for debugging
            try:
                with open("debug_extraction.html", "w", encoding="utf-8") as f:
                    f.write(self.driver.page_source)
                print("Saved debug_extraction.html for inspection")
            except:
                print("Could not save debug file")
        
        return voter_data
    
    def enter_voter_info(self, id_number):
        """Enter voter ID and solve captcha"""
        try:
            # Navigate to the voter information page
            print("Navigating to voter information page...")
            self.driver.get(self.website_url)
            
            # Wait for page to load completely
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            time.sleep(3)
            
            # Find the ID input field
            print("Looking for ID input field...")
            id_input = None
            
            # Try the most common selectors
            selectors = [
                "input#IDNumber",
                "input[name='IDNumber']", 
                "input[type='text']",
                "input.form-control"
            ]
            
            for selector in selectors:
                try:
                    id_input = self.driver.find_element(By.CSS_SELECTOR, selector)
                    print(f"Found input field using: {selector}")
                    break
                except:
                    continue
            
            if not id_input:
                # Last resort: get all text inputs and use the first one
                inputs = self.driver.find_elements(By.CSS_SELECTOR, "input[type='text']")
                if inputs:
                    id_input = inputs[0]
                    print("Using first text input field")
                else:
                    raise Exception("Could not find ID input field")
            
            # Enter the ID number
            id_input.clear()
            id_input.send_keys(id_number)
            print(f"Entered ID number: {id_number}")
            
            # Find reCAPTCHA
            print("Looking for reCAPTCHA...")
            site_key = self.find_recaptcha_elements()
            
            # Solve captcha
            captcha_solution = self.solve_recaptcha_v2(site_key, self.website_url)
            
            # Inject the captcha solution
            self.inject_recaptcha_solution(captcha_solution)
            
            # Wait a moment for the captcha to register
            time.sleep(3)
            
            # Find and click submit button
            submit_button = None
            submit_selectors = [
                "input[type='submit']",
                "button[type='submit']",
                ".btn-primary",
                "input[value*='Submit']",
                "input[value*='Search']"
            ]
            
            for selector in submit_selectors:
                try:
                    submit_button = self.driver.find_element(By.CSS_SELECTOR, selector)
                    print(f"Found submit button using: {selector}")
                    break
                except:
                    continue
            
            if submit_button:
                print("Submitting form...")
                submit_button.click()
                
                # Wait for navigation
                time.sleep(5)
                return True
            else:
                # In headless mode, we can't ask for manual submission
                print("Could not find submit button in headless mode.")
                return False
            
        except Exception as e:
            print(f"Error during voter info entry: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
    
    def get_voter_information(self, id_number):
        """Main method to get voter information"""
        try:
            self.setup_driver()
            success = self.enter_voter_info(id_number)
            
            if success:
                print("Form submitted! Checking for results...")
                
                # Check if we're on the results page
                current_url = self.driver.current_url
                if "My-ID-Information-Details" in current_url:
                    print("Successfully reached results page!")
                    
                    # Extract voter information
                    voter_data = self.extract_voter_information()
                    
                    # Display results
                    self.display_results(voter_data)
                    
                    # Save to JSON file
                    self.save_results(voter_data, id_number)
                    
                    return voter_data
                else:
                    print(f"Not on results page. Current URL: {current_url}")
                    print("This might indicate a captcha verification issue.")
                    
                    # Save current page for debugging
                    try:
                        with open("captcha_issue_debug.html", "w", encoding="utf-8") as f:
                            f.write(self.driver.page_source)
                        print("Saved captcha_issue_debug.html for inspection")
                    except:
                        print("Could not save debug file")
                    
                    return {"error": "Captcha verification may have failed"}
                    
            else:
                return {"error": "Failed to submit form"}
                
        except Exception as e:
            return {"error": f"Bot execution failed: {str(e)}"}
        finally:
            if self.driver:
                # No need to wait for user input in headless mode
                print("\nClosing browser...")
                try:
                    self.driver.quit()
                except:
                    pass  # Ignore errors during cleanup
    
    def display_results(self, voter_data):
        """Display voter information in a formatted way"""
        if "error" in voter_data:
            print(f"Error: {voter_data['error']}")
            return
        
        print("\n" + "="*60)
        print("VOTER INFORMATION RESULTS")
        print("="*60)
        
        fields = [
            ("Identity Number", "identity_number"),
            ("Name", "name"), 
            ("Ward", "ward"),
            ("Voting District", "voting_district"),
            ("Address", "address"),
            ("Voting Station", "voting_station")
        ]
        
        for display_name, data_key in fields:
            if data_key in voter_data and voter_data[data_key] != "Not found":
                print(f"{display_name}: {voter_data[data_key]}")
        
        print("="*60)
    
    def save_results(self, voter_data, id_number):
        """Save results to JSON file"""
        try:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"voter_info_{id_number}_{timestamp}.json"
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(voter_data, f, indent=2, ensure_ascii=False)
            print(f"Data saved to: {filename}")
        except Exception as e:
            print(f"Could not save results to file: {e}")

# Flask app setup
app = Flask(__name__)
bot = VoterInfoBot()

# Rate limiting setup
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

@app.route('/')
def serve_html():
    """Serve the ConnectVoterDrive.html file"""
    try:
        with open('ConnectVoterDrive.html', 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return "HTML file not found. Please ensure ConnectVoterDrive.html is in the same directory.", 404

@app.route('/verify_voter', methods=['POST'])
@limiter.limit("10 per minute")  # Prevent abuse
def verify_voter():
    """API endpoint to verify voter information"""
    data = request.get_json(silent=True)
    
    if not data:
        return jsonify({"error": "Invalid JSON data"}), 400
        
    id_number = data.get('id_number')
    
    if not id_number:
        return jsonify({"error": "ID number is required"}), 400
    
    # Validate ID number format (South African ID)
    if len(id_number) != 13 or not id_number.isdigit():
        return jsonify({"error": "Invalid ID number format. Must be 13 digits."}), 400
    
    print(f"Received verification request for ID: {id_number}")
    
    try:
        # Run the bot to get voter information
        voter_data = bot.get_voter_information(id_number)
        
        if "error" in voter_data:
            return jsonify({"error": voter_data["error"]}), 500
        
        # Format the response for the HTML form
        response_data = {
            "success": True,
            "fullName": voter_data.get("name", "Not found"),
            "age": calculate_age_from_id(id_number),
            "ward": voter_data.get("ward", "Not found"),
            "votingDistrict": voter_data.get("voting_district", "Not found"),
            "votingStation": voter_data.get("voting_station", voter_data.get("address", "Not found")),
            "address": voter_data.get("address", "Not found")
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        print(f"Error in verify_voter: {str(e)}")
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500

def calculate_age_from_id(id_number):
    """Calculate age from South African ID number"""
    try:
        year = int(id_number[:2])
        month = int(id_number[2:4])
        day = int(id_number[4:6])
        
        # Determine century (2000s if year < current year - 2000, else 1900s)
        current_year = int(time.strftime("%Y"))
        current_short_year = current_year % 100
        
        if year <= current_short_year:
            birth_year = 2000 + year
        else:
            birth_year = 1900 + year
        
        # Calculate age
        current_month = int(time.strftime("%m"))
        current_day = int(time.strftime("%d"))
        
        age = current_year - birth_year
        
        # Adjust if birthday hasn't occurred yet this year
        if current_month < month or (current_month == month and current_day < day):
            age -= 1
            
        return f"{age} years"
        
    except:
        return "Based on ID"

def run_flask_app():
    """Run the Flask app for production"""
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    
    print(f"Starting Flask server on port {port} (debug: {debug})")
    
    if debug:
        app.run(host='0.0.0.0', port=port, debug=True)
    else:
        # Use production WSGI server
        try:
            from waitress import serve
            print("Using Waitress production server")
            serve(app, host='0.0.0.0', port=port)
        except ImportError:
            print("Waitress not available, using Flask development server")
            app.run(host='0.0.0.0', port=port, debug=False)

def main():
    """Main function with two modes: Flask server or direct execution"""
    print("Voter Information Bot - Integrated Mode")
    print("=" * 50)
    print("1. Start Flask server (serves HTML and API)")
    print("2. Direct execution (command line)")
    
    choice = input("Choose mode (1 or 2): ").strip()
    
    if choice == "1":
        # Start Flask server
        run_flask_app()
    else:
        # Direct execution (original functionality)
        id_number = input("Enter the ID number: ").strip()
        
        if not id_number:
            print("No ID number provided. Exiting.")
            return
        
        if len(id_number) != 13 or not id_number.isdigit():
            print("Invalid ID number. Must be 13 digits.")
            return
        
        print(f"Processing ID: {id_number}")
        
        bot = VoterInfoBot()
        result = bot.get_voter_information(id_number)

# Error handlers
@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({
        "error": f"Rate limit exceeded: {e.description}"
    }), 429

@app.errorhandler(404)
def not_found_handler(e):
    return jsonify({
        "error": "Endpoint not found"
    }), 404

@app.errorhandler(500)
def internal_error_handler(e):
    return jsonify({
        "error": "Internal server error"
    }), 500

if __name__ == "__main__":
    main()