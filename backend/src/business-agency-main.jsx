import React from 'react';
import {createRoot} from 'react-dom/client';
import BusinessAgencyPreview from './BusinessAgencyPreview.jsx';
if(!import.meta.env.DEV){
  document.body.textContent='Business private development preview is unavailable here.';
}else{
  createRoot(document.getElementById('root')).render(<React.StrictMode><BusinessAgencyPreview/></React.StrictMode>);
}
