/** Academic vacancy regions are independent of career job-market scopes.
 * A missing/ambiguous country is explicitly "unknown", never inferred.
 */
export const ACADEMIC_REGIONS = Object.freeze([
  'north_america', 'latin_america', 'europe', 'middle_east',
  'asia', 'oceania', 'africa', 'unknown',
]);
export const REGION_LABELS = Object.freeze({
  en: {
    north_america: 'North America', latin_america: 'Latin America',
    europe: 'Europe (incl. UK)', middle_east: 'Middle East',
    asia: 'Asia', oceania: 'Oceania', africa: 'Africa',
    unknown: 'Other / unspecified',
  },
  fa: {
    north_america: 'آمریکای شمالی', latin_america: 'آمریکای لاتین',
    europe: 'اروپا (شامل بریتانیا)', middle_east: 'خاورمیانه',
    asia: 'آسیا', oceania: 'اقیانوسیه', africa: 'آفریقا',
    unknown: 'سایر / مکان نامشخص',
  },
});
const normalize = value => String(value || '').normalize('NFKD').toLowerCase()
  .replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]/g, '');
const NAMES = {
  north_america: ['US', 'USA', 'United States', 'United States of America',
    'America', 'Canada', 'CA', 'CAN'],
  latin_america: ['Mexico', 'MX', 'Brazil', 'BR', 'Argentina', 'Chile', 'Colombia',
    'Peru', 'Costa Rica', 'Ecuador', 'Uruguay', 'Paraguay', 'Venezuela',
    'Bolivia', 'Panama', 'Guatemala', 'Cuba', 'Dominican Republic'],
  europe: ['United Kingdom', 'UK', 'GB', 'Great Britain', 'England', 'Scotland',
    'Wales', 'Northern Ireland', 'Ireland', 'Germany', 'DE', 'France', 'FR',
    'Netherlands', 'NL', 'Belgium', 'BE', 'Switzerland', 'CH', 'Austria', 'AT',
    'Italy', 'IT', 'Spain', 'ES', 'Portugal', 'PT', 'Denmark', 'DK',
    'Norway', 'NO', 'Sweden', 'SE', 'Finland', 'FI', 'Iceland', 'IS',
    'Poland', 'PL', 'Czech Republic', 'Czechia', 'CZ', 'Slovakia',
    'Hungary', 'HU', 'Romania', 'Bulgaria', 'Croatia', 'Slovenia',
    'Estonia', 'Latvia', 'Lithuania', 'Luxembourg', 'Greece', 'Cyprus',
    'Malta', 'Serbia', 'Bosnia and Herzegovina', 'Ukraine', 'Moldova'],
  middle_east: ['Iran', 'IR', 'United Arab Emirates', 'UAE', 'AE', 'Saudi Arabia',
    'SA', 'Israel', 'IL', 'Turkey', 'Türkiye', 'TR', 'Qatar', 'QA',
    'Bahrain', 'Kuwait', 'Oman', 'Jordan', 'Lebanon', 'Iraq', 'Egypt',
    'Yemen', 'Palestine'],
  asia: ['India', 'IN', 'China', 'CN', 'Japan', 'JP', 'South Korea', 'Korea',
    'Republic of Korea', 'KR', 'Taiwan', 'TW', 'Singapore', 'SG',
    'Malaysia', 'MY', 'Indonesia', 'ID', 'Thailand', 'TH',
    'Vietnam', 'VN', 'Pakistan', 'PK', 'Bangladesh', 'Nepal',
    'Sri Lanka', 'Philippines', 'PH', 'Hong Kong', 'HK',
    'Kazakhstan', 'Uzbekistan', 'Mongolia'],
  oceania: ['Australia', 'AU', 'New Zealand', 'NZ', 'Fiji', 'Papua New Guinea'],
  africa: ['South Africa', 'ZA', 'Nigeria', 'NG', 'Kenya', 'KE', 'Ghana',
    'Morocco', 'Tunisia', 'Algeria', 'Ethiopia', 'Uganda', 'Tanzania',
    'Rwanda', 'Senegal', 'Egypt'],
};
const countries = new Map();
for (const [region, names] of Object.entries(NAMES))
  for (const name of names) countries.set(normalize(name), region);
export const academicRegion = country => countries.get(normalize(country)) || 'unknown';
