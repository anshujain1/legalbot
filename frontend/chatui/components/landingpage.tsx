'use client'
import React from 'react'
import Link from "next/link";

const landingpage = () => {
  return (
    <div>landingpage
        
      <Link
        href="/chat"
        className="px-4 py-2 bg-black text-white rounded"
      >
        Start Chat
      </Link>
    </div>
  )
}

export default landingpage