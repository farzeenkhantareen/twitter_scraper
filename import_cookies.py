import json
import sys
from pathlib import Path

def convert_cookies(input_file_path: str, output_file_path: str):
    """Reads standard browser-exported cookie JSONs and converts them to Playwright format."""
    try:
        with open(input_file_path, "r", encoding="utf-8") as f:
            raw_cookies = json.load(f)
            
        if not isinstance(raw_cookies, list):
            # Check if it's already in Playwright format
            if isinstance(raw_cookies, dict) and "cookies" in raw_cookies:
                print("File is already in Playwright format. Copying directly.")
                with open(output_file_path, "w", encoding="utf-8") as out:
                    json.dump(raw_cookies, out, indent=4)
                return
            raise ValueError("Input JSON must be a list of cookies.")
            
        playwright_cookies = []
        for c in raw_cookies:
            # Skip cookies not relevant to Twitter/X
            domain = c.get("domain", "")
            if not ("twitter.com" in domain or "x.com" in domain):
                continue
                
            name = c.get("name")
            value = c.get("value")
            path = c.get("path", "/")
            secure = c.get("secure", True)
            httpOnly = c.get("httpOnly", False)
            
            # Map sameSite values (Chrome/Edge formats differ from Playwright)
            raw_same_site = str(c.get("sameSite", "Lax")).lower()
            if "no_restriction" in raw_same_site or "none" in raw_same_site:
                same_site = "None"
            elif "strict" in raw_same_site:
                same_site = "Strict"
            else:
                same_site = "Lax"
                
            # Map expiration
            expires = c.get("expirationDate") or c.get("expires")
            
            cookie_dict = {
                "name": name,
                "value": value,
                "domain": domain,
                "path": path,
                "secure": secure,
                "httpOnly": httpOnly,
                "sameSite": same_site
            }
            if expires is not None:
                cookie_dict["expires"] = int(expires)
                
            playwright_cookies.append(cookie_dict)
            
        playwright_format = {
            "cookies": playwright_cookies,
            "origins": []
        }
        
        # Ensure output directory exists
        Path(output_file_path).parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file_path, "w", encoding="utf-8") as f:
            json.dump(playwright_format, f, ensure_ascii=False, indent=4)
            
        print(f"Successfully converted and saved {len(playwright_cookies)} cookies to {output_file_path}")
    except Exception as e:
        print(f"Error converting cookies: {e}")

if __name__ == "__main__":
    # Default inputs
    input_path = "cookies.json"
    output_path = "sessions/auth.json"
    
    # Overrides via command line arguments
    if len(sys.argv) > 1:
        input_path = sys.argv[1]
    if len(sys.argv) > 2:
        output_path = sys.argv[2]
        
    convert_cookies(input_path, output_path)
