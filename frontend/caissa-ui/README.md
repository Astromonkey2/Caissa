# Caissa UI

React 19 + Vite 6 frontend, deployed on Vercel.

```bash
npm install
npm run dev       # dev server on http://localhost:3000
npm run build     # production build → dist/
npm run preview   # serve the production build locally
```

Set `VITE_API_URL` (Vercel → project → Environment Variables) to the public
URL of the FastAPI backend. Locally, `.env.development` points it at
`http://localhost:8000`.

See the root `README.md` for the full architecture.
