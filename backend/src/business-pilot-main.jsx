import React from "react";
import {createRoot} from "react-dom/client";
import BusinessLocalPilot from "./BusinessLocalPilot.jsx";

// Separate dev entry: no Stripe, Supabase, Meta, live app analytics,
// creator integrations, or production authentication are loaded.
if(!import.meta.env.DEV){
  document.body.textContent="Local pilot is unavailable outside development.";
}else{
  createRoot(document.getElementById("root")).render(
    <React.StrictMode><BusinessLocalPilot/></React.StrictMode>
  );
}
