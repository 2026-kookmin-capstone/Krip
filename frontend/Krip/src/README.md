# Source Structure

The frontend is organized by route-level pages and larger feature areas.

```txt
src/
├── App.tsx
├── main.tsx
├── api/
│   ├── client.ts
│   ├── friend.ts
│   ├── image.ts
│   ├── mate.ts
│   ├── searchHistory.ts
│   └── auth/
├── components/
│   └── AppShell.tsx
├── features/
│   ├── friend-chat/
│   │   ├── ChatPage.tsx
│   │   └── ChatRoomPage.tsx
│   ├── mate/
│   │   └── MatePage.tsx
│   ├── plan/
│   │   ├── AiPlanDesignPage.tsx
│   │   ├── AiPlanResultPage.tsx
│   │   ├── Manualplanpage.tsx
│   │   └── PlanSelectionPage.tsx
│   └── tour/
│       └── HomePage.tsx
├── pages/
│   ├── LoginPage.tsx
│   ├── RegisterPage.tsx
│   ├── MyPage.tsx
│   ├── MenuPage.tsx
│   └── PlaceholderPage.tsx
└── utils/
```

## Guidelines

- Keep simple standalone route screens in `pages/`.
- Move large domain screens into `features/{domain}/`.
- Keep shared API wrappers in `api/` until a feature grows enough to justify local API modules.
- Keep cross-feature layout and reusable UI in `components/`.
- Prefer adding feature-local `components/`, `types`, or helper files when a feature page becomes too large.
