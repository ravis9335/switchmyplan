// SwitchMyPlan Responsive JavaScript
// Handles responsive interactions for mobile devices

document.addEventListener('DOMContentLoaded', function() {
  // ===== MOBILE NAVIGATION =====
  setupMobileNavigation();
  
  // ===== FILTER SIDEBAR (for all-plans.html) =====
  setupFilterSidebar();
  
  // ===== RESPONSIVE PLAN CARDS =====
  setupResponsivePlanCards();
  
  // ===== FIX CAROUSEL OVERFLOW ISSUES =====
  fixCarouselOverflow();
  
  // ===== INITIALIZE RESPONSIVE CHECKS =====
  checkResponsiveElements();
  
  // Run on resize for responsive adjustments
  window.addEventListener('resize', debounce(function() {
    checkResponsiveElements();
    fixCarouselOverflow();
  }, 250));
  
  // Toggle mobile filters
  setupMobileFilters();
});

// Helper function to throttle resize events
function debounce(func, wait) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}

// Setup mobile filters
function setupMobileFilters() {
  // Toggle mobile filters
  const mobileFilterToggle = document.createElement('div');
  mobileFilterToggle.className = 'mobile-filter-toggle show-on-mobile';
  mobileFilterToggle.innerHTML = '<i class="ri-filter-line"></i> <span>Show Filters</span>';
  
  const filtersSidebar = document.getElementById('filtersSidebar');
  if (filtersSidebar) {
    filtersSidebar.parentNode.insertBefore(mobileFilterToggle, filtersSidebar);
    
    mobileFilterToggle.addEventListener('click', function() {
      filtersSidebar.classList.toggle('active');
      this.classList.toggle('active');
      this.querySelector('span').textContent = 
        this.classList.contains('active') ? 'Hide Filters' : 'Show Filters';
    });
    
    // Make filter sections collapsible
    const filterSections = document.querySelectorAll('.filter-section');
    filterSections.forEach(section => {
      const heading = section.querySelector('h3');
      if (heading) {
        heading.addEventListener('click', function() {
          section.classList.toggle('collapsed');
        });
      }
    });
  }
  
  // Adjust grid/list view buttons for mobile
  const viewButtons = document.querySelectorAll('button[onclick^="setViewMode"]');
  if (viewButtons.length) {
    viewButtons.forEach(btn => {
      btn.classList.add('px-mobile-4', 'py-mobile-2');
    });
  }
}

// Setup mobile navigation
function setupMobileNavigation() {
  const navbar = document.getElementById('navbar');
  if (!navbar) return;
  
  // Get or create the mobile menu
  let mobileMenu = document.getElementById('mobile-menu');
  if (!mobileMenu) {
    mobileMenu = document.createElement('div');
    mobileMenu.id = 'mobile-menu';
    mobileMenu.className = 'fixed inset-0 bg-white z-[999] flex-col items-center justify-center';
    mobileMenu.style.display = 'none';
    document.body.appendChild(mobileMenu);
  }
  
  // Style the mobile menu
  mobileMenu.style.padding = '4rem 2rem';
  mobileMenu.style.overflowY = 'auto';
  
  // Find existing mobile menu button or create one
  let mobileMenuButton = document.querySelector('.mobile-menu-button');
  if (!mobileMenuButton) {
    mobileMenuButton = document.createElement('button');
    mobileMenuButton.className = 'mobile-menu-button md:hidden';
    mobileMenuButton.setAttribute('aria-label', 'Toggle menu');
    mobileMenuButton.innerHTML = '<i class="ri-menu-line text-2xl"></i>';
    
    // Add the button to the navbar
    const navbarContainer = navbar.querySelector('.container');
    if (navbarContainer) {
      const logoElement = navbarContainer.querySelector('a[href="/"]');
      if (logoElement && logoElement.nextElementSibling) {
        navbarContainer.insertBefore(mobileMenuButton, logoElement.nextElementSibling);
      } else if (logoElement) {
        logoElement.insertAdjacentElement('afterend', mobileMenuButton);
      } else {
        navbarContainer.querySelector('.flex').appendChild(mobileMenuButton);
      }
    } else {
      navbar.appendChild(mobileMenuButton);
    }
  }
  
  // Clear existing content and create new content
  mobileMenu.innerHTML = '';
  
  // Create the mobile menu header with close button
  const menuHeader = document.createElement('div');
  menuHeader.className = 'flex justify-between items-center w-full mb-8 pb-4 border-b border-gray-200';
  
  // Create logo for mobile menu
  const logoClone = navbar.querySelector('a[href="/"]')?.cloneNode(true);
  if (logoClone) {
    menuHeader.appendChild(logoClone);
  } else {
    const defaultLogo = document.createElement('a');
    defaultLogo.href = '/';
    defaultLogo.className = 'text-3xl font-bold';
    defaultLogo.textContent = 'SwitchMyPlan';
    menuHeader.appendChild(defaultLogo);
  }
  
  // Create close button
  const closeButton = document.createElement('button');
  closeButton.id = 'close-menu';
  closeButton.className = 'text-gray-500 hover:text-gray-800';
  closeButton.setAttribute('aria-label', 'Close mobile menu');
  closeButton.innerHTML = '<i class="ri-close-line text-3xl"></i>';
  menuHeader.appendChild(closeButton);
  mobileMenu.appendChild(menuHeader);
  
  // Create menu links container
  const menuLinks = document.createElement('div');
  menuLinks.className = 'flex flex-col w-full space-y-6 text-xl';
  
  // Get links from desktop menu
  const desktopMenu = navbar.querySelector('.desktop-menu');
  if (desktopMenu) {
    const links = desktopMenu.querySelectorAll('a');
    links.forEach(link => {
      const newLink = link.cloneNode(true);
      newLink.className = 'py-3 px-4 rounded-lg hover:bg-gray-100 transition-colors';
      menuLinks.appendChild(newLink);
    });
  } else {
    // Fallback links if desktop menu doesn't exist
    const defaultLinks = [
      { href: 'all-plans.html', text: 'Plans' },
      { href: 'faq.html', text: 'FAQ' },
      { href: 'about.html', text: 'About' }
    ];
    
    defaultLinks.forEach(linkInfo => {
      const link = document.createElement('a');
      link.href = linkInfo.href;
      link.textContent = linkInfo.text;
      link.className = 'py-3 px-4 rounded-lg hover:bg-gray-100 transition-colors';
      menuLinks.appendChild(link);
    });
  }
  
  mobileMenu.appendChild(menuLinks);
  
  // Create CTA button
  const ctaButtons = navbar.querySelector('.md\\:flex.items-center.gap-4');
  if (ctaButtons) {
    const ctaClone = ctaButtons.querySelector('a')?.cloneNode(true);
    if (ctaClone) {
      ctaClone.className = 'mt-8 py-4 px-6 bg-accent text-white rounded-full text-center w-full';
      mobileMenu.appendChild(ctaClone);
    }
  } else {
    // Fallback CTA button
    const defaultCta = document.createElement('a');
    defaultCta.href = 'all-plans.html';
    defaultCta.textContent = 'Compare Plans';
    defaultCta.className = 'mt-8 py-4 px-6 bg-accent text-white rounded-full text-center w-full';
    mobileMenu.appendChild(defaultCta);
  }
  
  // Add event listeners for opening and closing menu
  mobileMenuButton.addEventListener('click', function() {
    mobileMenu.style.display = 'flex';
    document.body.style.overflow = 'hidden'; // Prevent scrolling when menu is open
  });
  
  closeButton.addEventListener('click', function() {
    mobileMenu.style.display = 'none';
    document.body.style.overflow = ''; // Restore scrolling
  });
  
  // Add event listeners to menu links to close menu when clicked
  const allMenuLinks = mobileMenu.querySelectorAll('a');
  allMenuLinks.forEach(link => {
    link.addEventListener('click', function() {
      mobileMenu.style.display = 'none';
      document.body.style.overflow = ''; // Restore scrolling
    });
  });
}

// Setup filter sidebar for all-plans.html
function setupFilterSidebar() {
  const filterSidebar = document.querySelector('.filter-sidebar');
  if (filterSidebar) {
    // Create toggle button if it doesn't exist
    if (!document.querySelector('.filter-toggle')) {
      const filterToggle = document.createElement('button');
      filterToggle.classList.add('filter-toggle');
      filterToggle.innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
        </svg>
        Filter Plans
      `;
      
      // Create backdrop
      const filterBackdrop = document.createElement('div');
      filterBackdrop.classList.add('filter-backdrop');
      
      // Add to DOM
      const filterContainer = filterSidebar.parentElement;
      if (filterContainer) {
        filterContainer.insertBefore(filterToggle, filterContainer.firstChild);
        document.body.appendChild(filterBackdrop);
      }
      
      // Toggle filter sidebar
      filterToggle.addEventListener('click', function() {
        filterSidebar.classList.add('active');
        filterBackdrop.classList.add('active');
      });
      
      // Close on backdrop click
      filterBackdrop.addEventListener('click', function() {
        filterSidebar.classList.remove('active');
        filterBackdrop.classList.remove('active');
      });
      
      // Create close button for filter sidebar
      const filterClose = document.createElement('button');
      filterClose.classList.add('filter-close');
      filterClose.innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
        </svg>
      `;
      filterClose.style.position = 'absolute';
      filterClose.style.top = '1rem';
      filterClose.style.right = '1rem';
      filterClose.style.background = 'transparent';
      filterClose.style.border = 'none';
      filterClose.style.cursor = 'pointer';
      
      filterSidebar.appendChild(filterClose);
      
      // Close on button click
      filterClose.addEventListener('click', function() {
        filterSidebar.classList.remove('active');
        filterBackdrop.classList.remove('active');
      });
    }
  }
}

// Fix carousel overflow issues
function fixCarouselOverflow() {
  // Find all carousel containers
  const carouselContainers = document.querySelectorAll('.plan-carousel-container, .plan-carousel');
  if (carouselContainers.length > 0) {
    carouselContainers.forEach(container => {
      // Ensure container has overflow hidden
      container.style.overflow = 'hidden';
      
      // Ensure container has proper width
      container.style.width = '100%';
      
      // Disable horizontal scroll and enable touch behaviors only for vertical scrolling
      container.style.touchAction = 'pan-y';
      
      // Set max-width to avoid layout overflow
      container.style.maxWidth = '100vw';
      
      // Ensure all child elements are contained
      Array.from(container.children).forEach(child => {
        child.style.maxWidth = '100%';
        child.style.boxSizing = 'border-box';
      });
    });
  }
  
  // Adjust plan cards in carousel for better containment
  const planCards = document.querySelectorAll('.plan-carousel .plan-card');
  if (planCards.length > 0) {
    planCards.forEach(card => {
      card.style.flexShrink = '0';
      card.style.maxWidth = '100%';
      card.style.boxSizing = 'border-box';
    });
  }
}

// Improve carousel navigation for touch devices
function setupCarouselNavigation() {
  // Get all carousel navigation buttons
  const carouselButtons = document.querySelectorAll('.carousel-button');
  if (carouselButtons.length > 0) {
    carouselButtons.forEach(button => {
      // Increase tap target size for mobile
      button.style.minWidth = '44px';
      button.style.minHeight = '44px';
      
      // Add touch feedback
      button.addEventListener('touchstart', function() {
        this.style.transform = 'translateY(-50%) scale(0.95)';
      });
      
      button.addEventListener('touchend', function() {
        this.style.transform = 'translateY(-50%) scale(1)';
      });
    });
  }
}

// Setup responsive plan cards
function setupResponsivePlanCards() {
  const planCards = document.querySelectorAll('.plan-card');
  if (planCards.length > 0) {
    planCards.forEach(card => {
      // Ensure proper sizing
      card.style.boxSizing = 'border-box';
      
      // Add responsive classes
      if (window.innerWidth < 768) {
        // Compact layout for mobile
        card.classList.add('plan-card-mobile');
      } else {
        card.classList.remove('plan-card-mobile');
      }
    });
  }
  
  // Also set up carousel navigation
  setupCarouselNavigation();
}

// Check for responsive elements and apply additional styling if needed
function checkResponsiveElements() {
  const isMobile = window.innerWidth < 768;
  const isTablet = window.innerWidth >= 768 && window.innerWidth < 1024;
  
  // Apply responsive classes to body
  if (isMobile) {
    document.body.classList.add('is-mobile');
    document.body.classList.remove('is-tablet', 'is-desktop');
  } else if (isTablet) {
    document.body.classList.add('is-tablet');
    document.body.classList.remove('is-mobile', 'is-desktop');
  } else {
    document.body.classList.add('is-desktop');
    document.body.classList.remove('is-mobile', 'is-tablet');
  }
  
  // Re-run setup functions on major viewport changes
  setupResponsivePlanCards();
} 