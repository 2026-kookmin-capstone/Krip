// Gemini API 직접 호출 (AI팀 제공 로직 기반)

const GEMINI_API_KEY = 'AIzaSyDi4HGacT_xRIwKocSVHpBTbthhtFPEetw';
const GEMINI_MODEL = 'gemini-2.5-flash';
const GEMINI_URL = `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent?key=${GEMINI_API_KEY}`;

const SYSTEM_PROMPT = `You are an expert menu translator and data extractor for foreign tourists visiting South Korea.
Analyze the image and extract the information STRICTLY in the specified JSON format.
[RULES - CRITICAL]
1. NO Autocorrection: Extract the original Korean text EXACTLY as it appears. Do NOT fix typos.
2. English Translation: Provide a natural English translation for the menu name.
3. English Description: Provide a short, easy-to-understand English description of the dish.
4. Price Formatting: Extract the price as an integer. Remove all commas and currency symbols.
5. Category Classification: Classify each item into exactly one of these categories:
   - "메인메뉴": Main dishes, soups, rice dishes, noodles, grilled items
   - "사이드": Side dishes, appetizers, small plates
   - "음료/주류": All drinks including water, juice, soju, beer, makgeolli, wine
   - "디저트": Desserts, ice cream, cakes, sweet items
   - "기타": Set menus, combos, or anything that doesn't fit above
[JSON OUTPUT FORMAT]
{
  "restaurant_name": "String",
  "menus": [
    {
      "original_name": "String",
      "english_name": "String",
      "description": "String",
      "price": Integer,
      "category": "String"
    }
  ]
}`;

export type MenuCategory = '메인메뉴' | '사이드' | '음료/주류' | '디저트' | '기타';

export interface MenuItem {
  original_name: string;
  english_name: string;
  description: string;
  price: number;
  category: MenuCategory;
}

export interface OcrSingleResponse {
  restaurant_name?: string;
  menus: MenuItem[];
}

// File → base64 변환
const fileToBase64 = (file: File): Promise<string> =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      // "data:image/jpeg;base64,xxxx" → "xxxx" 부분만 추출
      resolve(result.split(',')[1]);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });

/**
 * 이미지 1장 → Gemini API로 메뉴 OCR
 */
export const ocrMenuSingle = async (file: File): Promise<OcrSingleResponse> => {
  const base64 = await fileToBase64(file);

  const response = await fetch(GEMINI_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      system_instruction: {
        parts: [{ text: SYSTEM_PROMPT }],
      },
      contents: [
        {
          parts: [
            { text: 'Extract the menu information according to the rules.' },
            { inline_data: { mime_type: file.type, data: base64 } },
          ],
        },
      ],
      generationConfig: {
        response_mime_type: 'application/json',
      },
    }),
  });

  if (!response.ok) {
    throw new Error(`Gemini API 오류: ${response.status}`);
  }

  const data = await response.json();
  const text = data.candidates?.[0]?.content?.parts?.[0]?.text;
  if (!text) throw new Error('Gemini 응답 파싱 실패');

  return JSON.parse(text) as OcrSingleResponse;
};
