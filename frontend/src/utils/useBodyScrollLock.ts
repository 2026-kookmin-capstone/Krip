import { useEffect } from "react";

let lockCount = 0;
let scrollY = 0;
let restoreBodyStyles: Partial<CSSStyleDeclaration> | null = null;
let restoreDocumentStyles: Partial<CSSStyleDeclaration> | null = null;

export function useBodyScrollLock(locked: boolean): void {
  useEffect(() => {
    if (!locked || typeof window === "undefined") return;

    lockBodyScroll();

    return () => {
      unlockBodyScroll();
    };
  }, [locked]);
}

function lockBodyScroll(): void {
  lockCount += 1;
  if (lockCount > 1) return;

  const { body, documentElement } = document;
  scrollY = window.scrollY || documentElement.scrollTop || 0;
  const scrollbarWidth = window.innerWidth - documentElement.clientWidth;

  restoreBodyStyles = {
    overflow: body.style.overflow,
    position: body.style.position,
    top: body.style.top,
    left: body.style.left,
    right: body.style.right,
    width: body.style.width,
    paddingRight: body.style.paddingRight,
  };
  restoreDocumentStyles = {
    overscrollBehavior: documentElement.style.overscrollBehavior,
  };

  body.style.overflow = "hidden";
  body.style.position = "fixed";
  body.style.top = `-${scrollY}px`;
  body.style.left = "0";
  body.style.right = "0";
  body.style.width = "100%";
  if (scrollbarWidth > 0) {
    body.style.paddingRight = `${scrollbarWidth}px`;
  }
  documentElement.style.overscrollBehavior = "none";
}

function unlockBodyScroll(): void {
  lockCount = Math.max(0, lockCount - 1);
  if (lockCount > 0) return;

  const { body, documentElement } = document;

  if (restoreBodyStyles) {
    body.style.overflow = restoreBodyStyles.overflow ?? "";
    body.style.position = restoreBodyStyles.position ?? "";
    body.style.top = restoreBodyStyles.top ?? "";
    body.style.left = restoreBodyStyles.left ?? "";
    body.style.right = restoreBodyStyles.right ?? "";
    body.style.width = restoreBodyStyles.width ?? "";
    body.style.paddingRight = restoreBodyStyles.paddingRight ?? "";
  }
  if (restoreDocumentStyles) {
    documentElement.style.overscrollBehavior =
      restoreDocumentStyles.overscrollBehavior ?? "";
  }

  restoreBodyStyles = null;
  restoreDocumentStyles = null;
  window.scrollTo(0, scrollY);
}
