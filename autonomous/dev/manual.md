# For Luka — Action Items & Setup Notes

> Things that require manual action or credentials that the autonomous agent cannot provide.

 Yandex Metrica                                                                                                                             
                                                                                                                                             
  1. Go to https://oauth.yandex.ru/ → create an app (or use existing)                                                                        
    - Permissions: metrika:read                                                                                                              
  2. Get an OAuth token: https://oauth.yandex.ru/authorize?response_type=token&client_id=YOUR_APP_ID                                       
  3. Find your counter ID in Metrica dashboard (the number in the URL or settings)                                                           
  4. Fill in config/backend.env:                                                                                                             
  YANDEX_METRICA_TOKEN=your_oauth_token                                                                                                      
  YANDEX_METRICA_COUNTER_ID=your_counter_id                                                                                                  
                                                                                                                                             
  Cloudflare                                                                                                                                 
                                                                                                                                             
  1. Go to https://dash.cloudflare.com/profile/api-tokens → Create Token                                                                     
    - Template: "Read analytics & logs" or custom with Zone.Analytics:Read                                                                   
    - Zone: select republicmag.io                                         
  2. Find Zone ID on the republicmag.io overview page in Cloudflare dashboard (right sidebar)                                                
  3. Fill in config/backend.env:                                                                                                             
  CLOUDFLARE_API_TOKEN=your_api_token                                                                                                        
  CLOUDFLARE_ZONE_ID=your_zone_id     

