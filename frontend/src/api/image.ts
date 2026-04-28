import client from "./client";
import { API_BASE_URL } from "./auth/config";

export interface UploadedImage {
  image_url: string;
}

export interface UploadImagesResponse {
  images: UploadedImage[];
}

export async function uploadImages(files: File[]): Promise<UploadImagesResponse> {
  const data = await postImageForm(files);
  const images = normalizeUploadedImages(data);

  if (images.length === 0) {
    throw new Error("Image upload completed, but no image URL was returned.");
  }

  return { images };
}

async function postImageForm(files: File[]): Promise<unknown> {
  const formData = new FormData();
  files.forEach((file) => {
    formData.append("files", file);
  });

  const { data } = await client.post<unknown>("/api/tripmate/images", formData, {
    timeout: 30000,
  });
  return data;
}

function normalizeUploadedImages(data: unknown): UploadedImage[] {
  const payload = data as {
    images?: Array<{ image_url?: string; imageUrl?: string; url?: string } | string>;
    image_urls?: string[];
    imageUrls?: string[];
    urls?: string[];
    image_url?: string;
    imageUrl?: string;
    url?: string;
  };

  const values = [
    ...(Array.isArray(payload.images) ? payload.images : []),
    ...(Array.isArray(payload.image_urls) ? payload.image_urls : []),
    ...(Array.isArray(payload.imageUrls) ? payload.imageUrls : []),
    ...(Array.isArray(payload.urls) ? payload.urls : []),
    payload.image_url,
    payload.imageUrl,
    payload.url,
  ];

  return values
    .map((item) => {
      if (typeof item === "string") return item;
      return item?.image_url || item?.imageUrl || item?.url || "";
    })
    .filter(Boolean)
    .map((url) => ({ image_url: toAbsoluteImageUrl(url) }));
}

function toAbsoluteImageUrl(url: string): string {
  const cleanUrl = url.trim().replace(/^<|>$/g, "");
  if (/^https?:\/\//i.test(cleanUrl)) return cleanUrl;
  return new URL(cleanUrl, API_BASE_URL).toString();
}
